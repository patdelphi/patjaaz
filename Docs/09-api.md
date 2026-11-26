# Jaaz 后端 HTTP 与实时事件接口说明

## 1. 鉴权接口（`/api/auth`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/auth/status` | 查询是否启用访问码门禁及当前会话是否已登录 |
| `POST` | `/api/auth/login` | 提交 `{"code": "..."}` 校验访问码并签发 `HttpOnly` HMAC Cookie（连续 5 次失败锁定 15 分钟） |
| `POST` | `/api/auth/logout` | 注销当前会话并主动断开关联 Socket.IO 连接 |

## 2. 画布与媒体文件接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/canvas/list` | 获取画布列表（按更新时间倒序） |
| `POST` | `/api/canvas/create` | 创建画布；`messages` 为空时仅创建空白画布不触发智能体 |
| `GET` | `/api/canvas/{id}` | 读取指定画布元素、文件映射与关联聊天会话 |
| `POST` | `/api/canvas/{id}/save` | 保存画布数据；服务端持画布互斥锁并保留前端尚未感知的新生成媒体 |
| `POST` | `/api/canvas/{id}/ops` | 元素级增量同步（`upsert` / `delete`），降低大画布高频保存体积 |
| `GET / POST` | `/api/canvas/{id}/snapshots` | 查询或手动创建画布历史版本快照 |
| `POST` | `/api/canvas/{id}/snapshots/{snap_id}/restore` | 在事务中回退指定画布至历史快照（回退前自动备份当前现场） |
| `POST` | `/api/canvas/{id}/rename` | 重命名画布 |
| `DELETE` | `/api/canvas/{id}/delete` | 事务级联删除画布及其聊天会话与消息 |
| `POST` | `/api/upload_image` | 上传并校验图像文件，返回 `{"file_id", "width", "height", "url"}` |
| `GET` | `/api/file/{file_id}` | 安全读取 `user_data/files` 下的图片、视频或音频文件 |

## 3. 对话与任务控制接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chat` | 提交聊天与生成请求，后台异步执行 LangGraph 与 ComfyUI 任务 |
| `GET` | `/api/chat/status/{session_id}` | 查询指定会话后台任务活跃状态、当前节点文本与终态 |
| `POST` | `/api/cancel/{session_id}` | 取消后台任务并联动调用远端 ComfyUI `/queue` 删除与 `/interrupt` |
| `GET` | `/api/list_models` | 返回已配置文本模型与可用生成工具汇总 |
| `GET` | `/api/list_tools` | 返回当前 `enabled=1` 的工作流工具列表 |

## 4. 设置与 ComfyUI 管理接口（`/api/settings`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET / POST` | `/api/config` | 读取（密钥掩码）与保存提供商及模型配置 |
| `POST` | `/api/settings/test_llm` | 按协议测试 LLM 接口连通性与延迟 |
| `GET / POST` | `/api/settings/system_prompt` | 读取与持久化服务端自定义系统提示词 |
| `GET / POST / PUT / DELETE` | `/api/settings/comfyui/instances*` | ComfyUI 多实例增删改查与 `/check` 健康探测 |
| `GET / POST / PUT / DELETE` | `/api/settings/comfyui/workflows*` | 工作流列表、成对导入、目录扫描、启停切换、`source/` 检测与 AI 自动解析导入 |

## 5. 创作与长片工作台接口（`/api/studio`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/studio/assets` | 跨全量画布按关键词与类型（图像/视频/音频）检索历史生成资产 |
| `GET / POST` | `/api/studio/templates` | 读取内置分镜模板与保存用户自定义参数化提示词模板 |
| `POST` | `/api/studio/plan_storyboard` | 将多行剧本或分镜列表原子铺排为角色设定框、水平分镜泳道、脚本卡、块箭头与递增角标 |
| `POST` | `/api/studio/batch_expand` | 解析 CSV/TSV 或单列变量文本并展开批量提示词 |
| `POST` | `/api/studio/compose_video` | 调用内置 `ffmpeg` 执行多段裁剪、转场、背景配乐侧链闪避（`bgm_audio`）、响度均衡、硬烧录字幕与片头片尾精装合片 |
| `POST` | `/api/studio/tts` | 多源语音合成（OpenAI / DashScope `qwen-tts` / 本机离线中文语音兜底）并写入画布音频卡 |
| `POST` | `/api/studio/extract_audio` | 从指定视频剥离 48kHz 立体声 MP3 音频卡片并写入画布 |
| `POST` | `/api/studio/extract_frame` | 提取视频首帧、尾帧或指定秒数关键帧 PNG 并写入画布血缘供长片接力 |
| `POST` | `/api/studio/prepare_mask_guide` | 将画布原图与涂抹遮罩合成为带红色半透明选区与外接红框的视觉引导图（`<Picture 2>`） |
| `GET` | `/api/studio/upscale_jobs` | 查询全部分块 `SeedVR2` 超分任务的进度与断点快照 |
| `POST` | `/api/studio/upscale_chunked` | 按远端内存自动计算安全切片秒数启动或断点续跑长视频超分并无损合流音轨 |
| `POST` | `/api/studio/hot_resume_colab` | 事务热更新 Colab 隧道地址、清空过期上传缓存、探测硬件并返回待续跑队列 |
| `GET` | `/api/studio/file_mappings` | 查询（`?refresh=true` 增量扫描补全）本地短 ID 文件与 `H:` 云盘双向映射表 |
| `GET` | `/api/studio/orphan_files` | 只读扫描未绑定任何画布或未完成超分任务的孤立临时切片与媒体文件 |
| `POST` | `/api/studio/cleanup_orphans` | 在显式传入 `confirm: true` 且二次核验零画布引用后安全清理已勾选孤立文件 |
| `GET` | `/api/studio/canvas_health/{canvas_id}` | 巡检指定画布全部媒体元素的本地文件存在性、血缘覆盖与云盘备份状态 |
| `GET` | `/api/studio/export_bundle/{canvas_id}` | 将画布 JSON、制片血缘单、云盘映射 CSV、字幕草稿及关联媒体一键打包为 `.zip` 下载 |

## 6. Socket.IO `session_update` 核心事件

- `delta` / `all_messages` / `done` / `error`：流式文本增量、消息同步、回合结束与错误通知。
- `tool_call` / `tool_call_arguments` / `tool_call_progress` / `tool_call_result`：工具调用及 ComfyUI 实时节点/百分比进度。
- `image_generated` / `video_generated` / `audio_generated` / `canvas_elements_updated`：新生成图像、视频、音频元素及原生画布排版工具落盘后的实时同步事件。
