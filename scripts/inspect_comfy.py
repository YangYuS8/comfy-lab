#!/usr/bin/env python3
"""Inspect a reachable ComfyUI instance using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_json(base_url: str, path: str, timeout: float) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} returned HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach {url}: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect ComfyUI service, models, and nodes")
    parser.add_argument(
        "--url",
        default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"),
        help="ComfyUI base URL; defaults to COMFY_URL or http://127.0.0.1:8188",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, help="Write the complete JSON report to this path")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the complete report instead of a compact summary",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "errors": {},
    }

    try:
        report["system_stats"] = get_json(base_url, "/system_stats", args.timeout)
    except RuntimeError as exc:
        report["errors"]["system_stats"] = str(exc)

    try:
        categories = get_json(base_url, "/models", args.timeout)
        report["model_categories"] = categories
        models: dict[str, list[str]] = {}
        for category in categories:
            path = "/models/" + urllib.parse.quote(str(category), safe="")
            try:
                value = get_json(base_url, path, args.timeout)
                models[str(category)] = value if isinstance(value, list) else []
            except RuntimeError as exc:
                report["errors"][f"models/{category}"] = str(exc)
        report["models"] = models
    except RuntimeError as exc:
        report["errors"]["models"] = str(exc)

    try:
        object_info = get_json(base_url, "/object_info", args.timeout)
        report["nodes"] = object_info
    except RuntimeError as exc:
        report["errors"]["object_info"] = str(exc)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.full:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        model_map = report.get("models", {})
        model_count = sum(len(items) for items in model_map.values())
        node_count = len(report.get("nodes", {}))
        summary = {
            "base_url": base_url,
            "reachable": "system_stats" in report or "model_categories" in report,
            "model_categories": len(model_map),
            "model_files": model_count,
            "node_types": node_count,
            "errors": report["errors"],
            "report_file": str(args.output) if args.output else None,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not ("system_stats" in report or "model_categories" in report):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
