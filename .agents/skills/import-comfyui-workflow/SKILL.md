---
name: import-comfyui-workflow
description: 当用户给出 ComfyUI 导出的 API JSON 工作流文件或要求导入/配置/停用 ComfyUI 工作流时使用本技能，帮助用户直接分析节点、生成并校验 jaaz.workflow.json、写入项目 workflows/ 目录并完成入库生效。
---

# 导入 ComfyUI 工作流到 Jaaz

当用户只提供了一个 ComfyUI 导出的 `*.api.json` 文件（或一句简单说明）时，按以下 4 步直接帮用户完成全部导入，无需用户手工编写或配置节点：

## 第 1 步：提取工作流节点摘要

运行项目内 CLI 工具提取过滤连线后的节点与可选 ComfyUI `/object_info` 枚举列表：

```powershell
server\.venv\Scripts\python.exe server\scripts\workflow_cli.py inspect "<用户提供的.api.json路径>"
```

若本机或远端 ComfyUI 实例正在运行（例如 `http://127.0.0.1:8188`），附加 `--comfy-url "http://127.0.0.1:8188"` 以获取准确下拉枚举项（例如 `"1:1 (Square)"`）：

```powershell
server\.venv\Scripts\python.exe server\scripts\workflow_cli.py inspect "<用户提供的.api.json路径>" --comfy-url "http://127.0.0.1:8188"
```

若报错提示检测到编辑器画布 JSON（含 `nodes` / `links`），请告知用户在 ComfyUI 中开启 **Dev Mode** 后重新通过 **Export (API)** 导出。

## 第 2 步：分析节点并生成 `jaaz.workflow.json`

参考 [workflows/jaaz.workflow.schema.json](../../../workflows/jaaz.workflow.schema.json) 与 [workflows/README.md](../../../workflows/README.md) 生成配置 JSON：

1. **精准映射 `node_id` 与 `node_input_name`**：严格使用第 1 步摘要中真实存在的节点 ID 与 `literal_inputs` 键名。
2. **只暴露高层必要参数**：
   - 文生图 (`t2i`)：正向提示词 (`positive_prompt`)、必要的画幅比例/宽高/像素档；
   - 图生图/编辑 (`i2i`/`inpaint`)：`LoadImage` 节点映射为 `type: "image"`, `required: true`（说明传入画布或用户上传的图片文件名），外加编辑指令提示词；
   - 文生视频/图生视频 (`t2v`/`i2v`) 或语音/音频 (`tts`/`music`)：设置准确的 `capability` 与 `output_kind`（`video` / `audio`）；
   - **不要暴露**工作流内固定的模型文件名（`ckpt_name`/`unet_name`/`vae_name`/`lora_name`）、固定采样器/步数/CFG 或随机种子（保持 `seed_strategy: "random"` 由后端自动处理）。
3. **写好工具 `description`**：用清晰中文说明工作流用途、必填参数、枚举值必须原样传入的限制，以及哪些设置已由工作流内部固定，不要让 Agent 乱传额外字段。

## 第 3 步：严格校验并安装到 `workflows/` 与数据库

将生成好的配置文件写入临时文件后运行安装命令（自动执行 `validate_workflow_pack`、落盘到 `workflows/<name>/{workflow.api.json, jaaz.workflow.json}` 并写入 SQLite 数据库）：

```powershell
server\.venv\Scripts\python.exe server\scripts\workflow_cli.py install "<workflow.api.json>" "<生成的jaaz.workflow.json>"
```

若返回校验报错（例如 `node_id` 或 `node_input_name` 不匹配），根据错误信息直接修正配置并重新运行 `install`。

## 第 4 步：管理启停开关与查看

- 导入后默认 `enabled: true`（对话 Agent 立即可选用）；如需先导入但不让 Agent 选用，在 `install` 加 `--disabled` 或运行：
  ```powershell
  server\.venv\Scripts\python.exe server\scripts\workflow_cli.py disable "<workflow_name>"
  ```
- 若 Jaaz 服务端已在运行，用户只需打开或刷新「设置 -> ComfyUI」页面即可自动同步并直接用 Switch 开关启停；若服务端正在从头启动，重启即自动扫描 `workflows/` 生效。
