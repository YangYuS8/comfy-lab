#!/usr/bin/env python3
"""Submit an API-format ComfyUI workflow, wait for completion, and download outputs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def request_json(
    base_url: str,
    path: str,
    *,
    payload: Any | None = None,
    timeout: float = 30.0,
) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}: {body[:2000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc.reason}") from exc


def parse_override(raw: str) -> tuple[str, str, Any]:
    if "=" not in raw or "." not in raw.split("=", 1)[0]:
        raise ValueError(f"Invalid --set value {raw!r}; expected NODE_ID.FIELD=JSON_VALUE")
    target, raw_value = raw.split("=", 1)
    node_id, field = target.split(".", 1)
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return node_id, field, value


def apply_overrides(workflow: dict[str, Any], overrides: list[str]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for raw in overrides:
        node_id, field, value = parse_override(raw)
        if node_id not in workflow:
            raise KeyError(f"Workflow has no node ID {node_id!r}")
        node = workflow[node_id]
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise KeyError(f"Node {node_id!r} has no inputs object")
        if field not in inputs:
            raise KeyError(f"Node {node_id!r} has no input field {field!r}")
        old_value = inputs[field]
        inputs[field] = value
        applied.append(
            {"node_id": node_id, "field": field, "old": old_value, "new": value}
        )
    return applied


def wait_for_history(
    base_url: str,
    prompt_id: str,
    *,
    timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    quoted_id = urllib.parse.quote(prompt_id, safe="")
    last_entry: dict[str, Any] | None = None

    while time.monotonic() < deadline:
        history = request_json(base_url, f"/history/{quoted_id}", timeout=30.0)
        entry = history.get(prompt_id) if isinstance(history, dict) else None
        if isinstance(entry, dict):
            last_entry = entry
            status = entry.get("status", {})
            completed = status.get("completed") is True
            status_str = status.get("status_str")
            if completed or status_str in {"success", "error"}:
                return entry
            if entry.get("outputs") and status_str not in {"running", "pending"}:
                return entry
        time.sleep(poll_interval)

    detail = json.dumps(last_entry, ensure_ascii=False)[:1000] if last_entry else "no history"
    raise TimeoutError(f"Prompt {prompt_id} did not finish within {timeout}s; last state: {detail}")


def iter_file_refs(value: Any):
    if isinstance(value, dict):
        if "filename" in value and isinstance(value["filename"], str):
            yield value
        for child in value.values():
            yield from iter_file_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_file_refs(child)


def download_outputs(
    base_url: str,
    history_entry: dict[str, Any],
    output_dir: Path,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for ref in iter_file_refs(history_entry.get("outputs", {})):
        filename = ref["filename"]
        subfolder = str(ref.get("subfolder", ""))
        file_type = str(ref.get("type", "output"))
        key = (filename, subfolder, file_type)
        if key in seen:
            continue
        seen.add(key)

        query = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": file_type}
        )
        url = f"{base_url.rstrip('/')}/view?{query}"
        request = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(request, timeout=60.0) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {url} returned HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot download {url}: {exc.reason}") from exc

        relative = Path(subfolder) / filename if subfolder else Path(filename)
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        downloaded.append(
            {
                "filename": filename,
                "subfolder": subfolder,
                "type": file_type,
                "local_path": str(destination),
                "size_bytes": len(content),
            }
        )
    return downloaded


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an API-format ComfyUI workflow")
    parser.add_argument("workflow", type=Path)
    parser.add_argument(
        "--url",
        default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"),
        help="ComfyUI base URL; defaults to COMFY_URL or http://127.0.0.1:8188",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NODE_ID.FIELD=JSON_VALUE",
        help="Override one workflow input; may be supplied multiple times",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/latest"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/latest/run.json"))
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()

    document = json.loads(args.workflow.read_text(encoding="utf-8"))
    workflow = document.get("prompt", document)
    if not isinstance(workflow, dict):
        raise TypeError("Workflow must be an API-format JSON object")

    applied = apply_overrides(workflow, args.set)
    client_id = uuid.uuid4().hex
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()

    submission = request_json(
        args.url,
        "/prompt",
        payload={"prompt": workflow, "client_id": client_id},
        timeout=60.0,
    )
    prompt_id = submission.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {submission}")
    if submission.get("node_errors"):
        raise RuntimeError(
            "ComfyUI rejected workflow nodes: "
            + json.dumps(submission["node_errors"], ensure_ascii=False)
        )

    history_entry = wait_for_history(
        args.url,
        str(prompt_id),
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    downloaded = download_outputs(args.url, history_entry, args.output_dir)
    elapsed = time.monotonic() - started_monotonic

    status = history_entry.get("status", {})
    report = {
        "workflow": str(args.workflow),
        "comfy_url": args.url.rstrip("/"),
        "client_id": client_id,
        "prompt_id": prompt_id,
        "started_at": started_at.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "status": status,
        "overrides": applied,
        "downloaded_outputs": downloaded,
        "submission": submission,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if status.get("status_str") == "error":
        return 1
    if not downloaded:
        print("Warning: workflow completed but no downloadable outputs were found", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
