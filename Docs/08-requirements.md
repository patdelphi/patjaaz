# Jaaz 社区版需求说明

## 1. 产品定位与目标

Jaaz 社区版是本地优先的 AIGC 无限画布创作工作台。系统不绑定私有云端账号与计费服务，通过接入本地或远端 ComfyUI 实例与开放协议大语言模型，在同一块 Excalidraw 无限画布内完成脚本编排、文生图、多参考图编辑、图生视频、文生视频与音频生成。

## 2. 核心功能范围

### 2.1 无限画布与分镜创作
- 支持空白画布一键新建、重命名、删除及首页封面缩略图（图片优先，纯视频画布自动取视频帧）。
- 支持矩形、菱形、椭圆、文本、画笔、连接箭头、闭合多边形块箭头、Frame 分镜画框、橡皮擦、激光笔与自动递增序号标注（1, 2, 3...）。
- 支持画布内嵌图像、视频（悬停静音预览、有声切换、时间轴拖拽、单次点击直接拖拽移动）与音频播放卡片。
- 支持选中单元素或整组 Frame 分镜框一键加入聊天，以及针对图像/脚本的 AI 快捷指令菜单。
- 支持选中原始媒体打包导出，以及整张画布或选区导出为合成视频封面帧的 PNG/SVG。
- 用户直接粘贴或拖入画布的内联 Base64 图片自动上传外置为 `/api/file/<id>`，控制 SQLite 画布 JSON 体积。

### 2.2 ComfyUI 多实例与工作流包管理
- 支持多个 ComfyUI 实例配置（含反向代理子路径前缀、Bearer/Basic/自定义请求头鉴权、并发槽位控制与健康探测）。
- 采用 `<repo_root>/workflows/<name>/{workflow.api.json, jaaz.workflow.json}` 成对文件规范管理工作流，支持一键启停开关、节点校验、`workflows/source/` 原始导出检测与 AI 辅助解析入库。
- 支持上传文件 SHA-256 去重缓存；当远端实例重启清空 `input/` 目录时自动失效对应缓存并重传重试一次。
- 生图与长视频生成不设硬编码总超时，WebSocket 断线自动降级轮询 `/history`，后端重启后由 `job_recovery` 自动接管未完成远端任务并写回原画布。

### 2.3 多协议大模型与智能体协作
- 零额外依赖支持 `openai`、`anthropic`、`google`、`openai-compatible` 与 `ollama` 协议，提供密钥掩码与连接测试。
- 按能力将工具拆分为 `planner`、`image_creator`、`video_creator`、`audio_creator` 分组智能体，支持跨能力自动交接（Handoff）与 `<canvas_scene_context>` 画布场景实时感知。

## 3. 安全与非功能约束

- 文件路径访问统一经 `safe_join` 与 `safe_file_id_path` 校验，拦截目录穿越与任意文件删除。
- 支持 `.env` `JAAZ_ACCESS_CODE`（不少于 16 字符）+ HMAC 签名会话 Cookie + 登录限流保护 HTTP API 与 Socket.IO 连接。
- `GET /api/config` 与日志输出统一对 API Key、Bearer/Basic 凭据脱敏。
