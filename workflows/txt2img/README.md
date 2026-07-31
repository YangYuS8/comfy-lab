# Text-to-image workflows

本目录只保存可由 ComfyUI API 直接提交的工作流 JSON。

## 首个工作流

目标文件：

```text
sd15-basic-api.json
```

由 Luna 在 Fedora 的 ComfyUI 中完成：

1. 打开已经成功运行的 SD 1.5 基础文生图工作流。
2. 确认节点只依赖内置节点和清单中的 checkpoint。
3. 使用 ComfyUI 的 **Save (API Format)** / **导出 API 格式** 功能导出。
4. 用 `scripts/run_workflow.py` 真实提交并验证。
5. 将实际节点 ID 写入运行示例或报告。

不要把普通画布 Workflow JSON 误当成 API JSON。API 格式的顶层通常以节点 ID 为键，每个节点包含 `class_type` 和 `inputs`。
