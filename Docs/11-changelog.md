# Jaaz 变更记录（Changelog）

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
