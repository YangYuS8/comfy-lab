# comfy-lab

由 Agent 驱动的 ComfyUI 工作流实验仓库。

这里保存可复现的工作流、自动化脚本、模型清单和实验报告；不保存模型权重、批量输出和任何凭据。

## 架构

```text
你 / ChatGPT / Luna
        │
        │ Git + ComfyUI HTTP API
        ▼
Fedora 上的 ComfyUI ── NVIDIA GPU
```

浏览器画布主要用于可视化调试；稳定工作流应导出为 **API Format JSON**，再由脚本或 Agent 调用。

## 目录

```text
AGENTS.md                    Agent 操作规范
manifests/models.yaml        模型来源、路径、哈希与许可证
scripts/inspect_comfy.py     检查服务、模型与节点
scripts/run_workflow.py      参数化提交工作流并下载结果
workflows/                   API 格式工作流
reports/                     可复现实验报告
```

## 快速开始

```bash
git clone https://github.com/YangYuS8/comfy-lab.git
cd comfy-lab

export COMFY_URL='http://<Fedora-IP>:8188'
python scripts/inspect_comfy.py
```

运行已经导出的 API 工作流：

```bash
python scripts/run_workflow.py \
  workflows/txt2img/sd15-basic-api.json \
  --set '6.text="a small robot reading in a library"' \
  --set '3.seed=42'
```

`--set` 的格式为 `节点ID.输入字段=JSON值`。节点 ID 和字段名以导出的 API JSON 为准。

## 当前里程碑

第一阶段目标：让 Luna 不依赖浏览器点击，通过 ComfyUI API 完成一次 SD 1.5 文生图，并提交工作流、模型清单和运行报告。
