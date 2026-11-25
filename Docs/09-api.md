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

## 5. Socket.IO `session_update` 核心事件

- `delta` / `all_messages` / `done` / `error`：流式文本增量、消息同步、回合结束与错误通知。
- `tool_call` / `tool_call_arguments` / `tool_call_progress` / `tool_call_result`：工具调用及 ComfyUI 实时节点/百分比进度。
- `image_generated` / `video_generated` / `audio_generated`：新生成图像、视频、音频元素落盘后的实时画布同步事件。
