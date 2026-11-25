# Jaaz 变更记录（Changelog）

## 2026-11-25 — 阶段 P1–P4 执行链路加固、Agent 画布编排、深度交互与模块拆分

### 修复与加固（Fixed）
- **子图工具调用即时幂等落库（P1）**：`StreamProcessor` 在收到 `ToolMessage` 时立即按 `tool_call_id` 去重写入 `assistant(tool_calls)` 与 `tool` 消息，防止出图后上游总结阶段 `429` 限流或断网丢失工具历史。
- **ComfyUI 中间预览输出过滤（P1）**：支持 `jaaz.workflow.json` 的 `outputs` 白名单及终端保存节点（`SaveImage` / `SaveVideo` / `SaveAudio` / `VHS_VideoCombine`）自动过滤，剔除 `LoadVideo` / `LoadImage` / `PreviewImage` 中间预览产物。
- **跨模型家族显存自动释放（P1）**：`comfy_instance_service` 跟踪实例最近执行的模型家族，跨家族切换时自动调用 `/api/free` 释放闲置权重缓存。

### 新增（Added）
- **Python Agent 原生画布编排与指向式指令（P2 / A2 / A3 / A9）**：新增 `canvas_arrange_elements` 与 `canvas_connect_and_badge` 系统工具及 Socket.IO `canvas_elements_updated` 实时增量合并；在 `<canvas_scene_context>` 解析 `callout-badge`（`①②③`）附着的底层媒体与九宫格坐标；新增 `context_compactor` 自动折叠早期 `write_plan` 与超长工具提示词参数。
- **画布深度交互、血缘谱系、增量同步与历史快照（P3 / G2 / E8 / X1 / C9 / C1 / C7 / C10 / C11）**：新增涂抹遮罩 PNG 导出、前后对比滑块、翻转/圆角、按 `Frame` 多格式/PDF 导出、`jaazLineage` 血缘溯源与换种子一键重抽、`/api/canvas/{id}/ops` 增量同步、图层管理与 SQLite 历史快照回退，以及视口外视频自动暂停。
- **创作工作台、TTS 配音、批量变量展开与内置 `ffmpeg` 自动剪辑拼接（P4 / M1 / E10 / V3 / V4 / W1 / W2）**：新增跨画布资产检索入画、分镜与提示词模板、CSV 表格变量批量展开、悬浮栏一键 TTS 配音；内置 `server/bin/ffmpeg.exe` 与 `ffprobe.exe` 零外部环境依赖执行，新增 `video_edit_and_stitch` 智能体工具支持单段截齐裁剪、48kHz 原生立体声音轨无缝串联、衔接处音画柔化转场及画布 `jaazLineage` 血缘溯源，并通过 `4 × 15s -> 60.0s` 1 分钟完整有声短片端到端实测验收。

### 工程治理（Changed）
- **超长模块拆分与脱敏日志统一（P4 / R-17 / R-19）**：将 `comfy_workflow_pack.py`、`db_service.py`、`comfyui_router.py`、`llm_adapters.py` 按职责拆分为 10 个不超过 600 行的模块并保留全部公开导出；将核心服务残余 `print` 收敛至 `get_sanitized_logger`。

## 2026-11-25 — 画质参数修复、全媒体边界闭环与 Stage C 工程治理

### 修复（Fixed）
- **MiniMax H3 生图过曝与画质劣化修复**：修正 `text2image_minimax_h3` 隐藏子图 `KSampler` 中误配的 `cfg: 8` 为蒸馏模型标准 `cfg: 1`（`steps: 8`），将 `megapixels` 默认值调整为 `2.0`、`enable_prompt_enhancer` 默认设为 `false`（由 Jaaz 智能体直接输出完整视觉提示词），消除高光死白、色阶断层及 24GB 显存环境下的多模型内存交换卡顿；同步将 `image_edit_multiref_minimax_h3` 采样步数提升至 `8` 步，修复 `ref2video_minimax_h3_ref2va` 调度器未经过 LoRA 切换节点的连线，并将首尾帧与文生视频默认画质对齐至 `0.9 MP` + 8 步 Turbo LoRA。
- **远端重启上传缓存失效自愈（R-10）**：当复用 SHA-256 上传缓存遇到远端 ComfyUI 重启清空 `input/` 报错时，自动失效缓存并重传重试一次。

### 新增（Added）
- **画布音频卡片（C5）**：支持 `audio/*` 输出落盘写入画布、实时广播 `audio_generated`、`<AudioElement>` 播放下载、重连恢复与选中引用加入对话。
- **画布导出视频封面合成**：右上角导出菜单新增整张画布/选区导出 PNG 与 SVG，自动截取视频帧合成封面避免空白框。
- **粘贴内联图片自动外置（C2）**：自动检测粘贴或拖入画布的 `data:image/*` 内联文件并上传替换为 `/api/file/<id>`。
- **画布创作交互增强（C4 / E5 / E9）**：新增画布顶部原生 `<progress>` 生成进度浮层、悬浮栏 AI 快捷动作菜单与底部工具栏自动递增序号标注。
- **服务端系统提示词持久化（R-26）**：新增 `GET/POST /api/settings/system_prompt` 并在聊天服务自动回退读取。

### 工程优化（Changed）
- **前端代码分包与严格检查（R-21 / R-22）**：配置 Vite `manualChunks` 拆分 `excalidraw`、`diagram`、`ui` 与框架依赖，懒加载 `SettingsDialog`；开启 `tsconfig.app.json` 的 `noUnusedLocals` 与 `noUnusedParameters` 并清零全部告警。
- **后端治理与测试提速（R-11 / R-18 / R-23 / R-24 / R-25）**：新增 `log_sanitizer` 凭据脱敏、Anthropic/Gemini `usage_metadata` 提取、`workflows/` 目录 `mtime` 指纹缓存、CLI 按需延迟导入及本地 `aiohttp` 假 ComfyUI 全链路测试；后端 107 项单测耗时从 28.68s 降至 8.64s。

## 2026-11-24 — M0 安全加固、M1 去云端与多实例工作流体系

- 完成路径安全、访问码 HMAC 会话、画布并发锁、去云端清理、SQLite v4 自动备份迁移、ComfyUI 多实例与 `workflows/` 成对工作流管理、三协议 LLM 适配、画布防碰撞排布、`<canvas_scene_context>` 场景感知及任务断线重启接管。
