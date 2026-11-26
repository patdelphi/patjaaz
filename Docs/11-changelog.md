# Jaaz 变更记录（Changelog）

## 2026-11-26 — 阶段 P5–P7 长片闭环、异构分流、17 套工作流全量纳管、遮罩引导重绘与导演时间轴

### 新增（Added）
- **云盘剩余 5 套工作流校准入库（P7-1）**：将 `text2image_MOSS`、`ImageEdit_MOSS`、`image_multiref_moss`、`ref2video_quad_minimax_h3_ref2va`、`ref2video_dual_minimax_h3_r2v` 校准连线与步数后标准化写入 `workflows/`（全仓库共 17 套成对工作流包），同步更新 `Docs/12-ComfyUI工作流完整使用说明.md`。
- **画布涂抹遮罩视觉引导重绘闭环（P7-2）**：新增 `visual_mask_guide_service.py`、`prepare_visual_mask_guide` 系统工具与 `POST /api/studio/prepare_mask_guide`，前端画笔涂抹提交时自动叠绘半透明红框引导图（`<Picture 2>`）配合原图（`<Picture 1>`）对接无遮罩槽大模型精准局部重绘。
- **导演分镜时间轴与前端按需懒加载（P7-3 / P7-4）**：新增 `StudioDirectorTimeline.tsx` 支持镜头上下排序、单镜起止秒裁剪、逐镜台词自动换算硬烧录时间轴、一键抽尾帧接力与分块超分；对 `CanvasExcali`、工作台抽屉与仅开发环境加载的 `RouterDevtools` 实施 `React.lazy` 拆分并细化 `manualChunks`。
- **异构双实例自动分流调度（P6-3）**：升级 `comfy_instance_service.resolve_instance`，同时配置多台实例时，重型 `NVFP4` 工作流（`MiniMax H3` / `SenseNova`）自动避开 `SM < 8.0` 或 `<16 GiB` 显存节点路由至 L4/A100 实例，`SeedVR2` 超分优先分流至在线次级 T4 或 `upscale` 节点并行执行。
- **多源旁白语音合成与视频音轨剥离（P6-2）**：新增 `local_audio_service.py` 与系统工具 `synthesize_speech_narration`、`extract_video_audio`，打通 OpenAI `/audio/speech`、阿里云百炼原生 `qwen-tts` 及 Windows 离线中文语音 + 内置 `ffmpeg` 响度均衡兜底，支持一键剥离视频音轨卡片。
- **短片制片工程包一键归档导出（P6-4）**：新增 `project_bundle_service.py` 与 `GET /api/studio/export_bundle/{canvas_id}`，将画布 `canvas.json`、UTF-8 BOM+CRLF 制片血缘单、云盘映射 CSV、SRT 字幕草稿与关联媒体打包为 `.zip` 供工作台一键下载；同步补齐 `Docs/09-api.md` 全量接口表。
- **长视频自动分块断点超分内置化（P5-1）**：新增 `long_video_pipeline_service.py`、`upscale_job_store.py` 与系统工具 `video_upscale_chunked`，根据远端 `/system_stats` 可用内存自动计算安全切片时长（如 50GiB 内存取 `15.0s`、28GiB 取 `10.0s`），通过内置 `server/bin/ffmpeg.exe` 预切片并逐块执行 `SeedVR2` 超分；Colab 断线时自动持久化 `paused_offline` 检查点，恢复后跳过已完成切片，并在合片阶段无损回灌原视频完整立体声音轨写入画布血缘。
- **角色定妆锚定与视频抽帧接力工具（P5-2）**：新增 `extract_video_frame` 系统工具与 `/api/studio/extract_frame` 接口，支持提取上一段视频尾帧、首帧或指定秒数关键帧 PNG 并挂载 `jaazLineage`，供下一段 `image2video_first_frame` 或 `ref2video_dual` 锁定人物面容与服饰衔接。
- **远端 GPU 规格自适应防呆与 Colab 换址热续跑（P5-3）**：新增 `gpu_compatibility_guard.py` 并在 `comfy_dynamic.py` 接入前置检测，自动拦截 Turing 及更早架构（如 Tesla T4 `SM 7.5` / `<16 GiB` 显存）运行 `NVFP4` 重型工作流并放行 `SeedVR2`，对 24GB 级显存执行 `>=12s` 长视频自动约束 `megapixels=0.45` 防 `VAEDecode` 溢出；新增 `POST /api/studio/hot_resume_colab` 事务更新隧道地址、清空过期上传缓存并探测显卡。
- **内置 `ffmpeg` 成片精装升级（P5-4）**：新增 `video_finishing_service.py`，扩展 `video_edit_and_stitch` 与 `/api/studio/compose_video` 支持 `loudnorm`（EBU R128 `-16 LUFS` 响度均衡）、Windows 路径转义硬烧录 SRT 字幕、片头标题渐显与片尾黑场音画淡出。
- **工作台「云盘映射与清理」面板（P5-5）**：新增 `storage_cleanup_service.py`、`studio_p5_routes.py` 与前端 `StudioMappingsAndCleanupTab.tsx`，提供 `file_mappings` 云盘双向映射响应式数据表、Colab 换址续跑控件，以及零画布引用核验的孤立临时切片只读扫描与显式二次确认删除模态框。

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
