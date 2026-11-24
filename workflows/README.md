# ComfyUI 外部工作流文件组目录 (`workflows/`)

本目录用于存放项目内可共享、可版本管理、可启停控制的 ComfyUI 工作流文件组。每个工作流由**一对文件**组成：

## 1. 支持的文件结构

- **子目录形式（推荐，管理端导入自动按此格式保存）：**
  ```text
  workflows/<workflow_name>/workflow.api.json
  workflows/<workflow_name>/jaaz.workflow.json
  ```
- **平铺成对形式：**
  ```text
  workflows/<workflow_name>.api.json
  workflows/<workflow_name>.jaaz.json
  ```
- **原始 API 工作流收件箱（`workflows/source/`）：**
  可将尚未配对 `jaaz.workflow.json` 的 ComfyUI **Export (API)** 原始 JSON 直接放入 `workflows/source/`（该目录会被工作流包扫描自动跳过，不会报错）：
  - 服务启动与设置页列表加载会自动检测 `workflows/source/` 中新增或变更的文件；
  - 默认只提示、不自动调用模型；需要在「设置 -> ComfyUI」手动打开“启动时自动导入”开关，或点击「AI 自动导入新文件」按钮，才会用已配置文本大模型生成配对配置并入库（会消耗 token）；
  - 打包后工作流目录位于用户数据目录 `workflows/`（可用环境变量 `JAAZ_WORKFLOWS_DIR` 指定），首次启动会把随包默认工作流复制过去，已有的不覆盖；
  - 也可由外部 AI Agent 执行 `server\.venv\Scripts\python.exe server\scripts\workflow_cli.py check-source` 逐一完成高精度的参数与说明补全后写入 `workflows/<name>/`。

> 注意：`workflow.api.json` / `<name>.api.json` 必须是从 ComfyUI 中通过 **Dev Mode -> Save / Export (API)** 导出的 API JSON（以节点 ID 为键、包含 `class_type` 与 `inputs`）。请勿直接放入包含 `nodes` / `links` 数组的编辑器画布 JSON。

## 2. 让 AI Agent 直接完成导入

### 方式 A：由外部 Coding AI Agent 一键导入

1. 把用户导出的 `*.api.json` 与说明交给当前对话中的 AI Agent（工作流 Schema 见 [jaaz.workflow.schema.json](./jaaz.workflow.schema.json)，配套 Skill 位于 `.agents/skills/import-comfyui-workflow/SKILL.md`）。
2. Agent 通过命令行执行：
   ```powershell
   server\.venv\Scripts\python.exe server\scripts\workflow_cli.py inspect "<你的workflow.api.json>"
   ```
3. Agent 自动分析节点、生成合规的 `jaaz.workflow.json`，再运行：
   ```powershell
   server\.venv\Scripts\python.exe server\scripts\workflow_cli.py install "<workflow.api.json>" "<jaaz.workflow.json>"
   ```
4. 文件自动落盘到 `workflows/<name>/` 并入库；刷新设置页或重启服务即可自动同步生效，可随时用 Switch 开关控制是否允许对话 Agent 选用。

### 方式 B：在管理界面中由内置 AI 解析导入

在「设置 -> ComfyUI -> 导入工作流」中切到默认 Tab「AI 自动解析导入」，上传单个 `.api.json` 并可附带一句描述后，点击 **AI 解析并直接导入**，系统将自动调用当前已配置的文本大模型生成配置、严格校验、落盘并刷新工具列表。

## 3. `jaaz.workflow.json` Schema v1 示例

```json
{
  "schema_version": 1,
  "name": "text2image_moss",
  "display_name": "MOSS 文生图",
  "capability": "t2i",
  "output_kind": "image",
  "enabled": true,
  "instance_id": "",
  "seed_strategy": "random",
  "description": "使用 MOSS 工作流根据提示词生成单张图像。",
  "inputs": [
    {
      "name": "positive_prompt",
      "type": "string",
      "required": true,
      "node_id": "6",
      "node_input_name": "text",
      "default_value": "",
      "description": "正向画面描述，支持中英文"
    },
    {
      "name": "aspect_ratio",
      "type": "enum",
      "required": true,
      "node_id": "19",
      "node_input_name": "aspect_ratio",
      "default_value": "1:1 (Square)",
      "options": ["1:1 (Square)", "16:9 (Widescreen)", "9:16 (Portrait Widescreen)"],
      "description": "画面比例，必须原样传入枚举项"
    }
  ]
}
```
