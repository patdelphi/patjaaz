# 清理 Jaaz 登录、会员与协议相关内容

## 完成内容

- [x] 移除 Jaaz 账号登录弹窗、账户菜单、余额/积分/充值显示、计费接口和登录自动弹窗。
- [x] 移除登录/余额门禁，社区版不再展示 Jaaz 账号云端模型。
- [x] 删除 Jaaz 云端模板分享弹窗及中英文文案。
- [x] 清理 README 中 Jaaz 登录与付费说明。
- [x] 删除根目录 LICENSE。
- [x] 清理中英文登录、余额、充值文案及相关公共导出。
- [x] 为 Jaaz 云端模型过滤添加纯函数回归测试。

## 保留内容

- 第三方网站登录说明和 Agent 浏览器登录功能。
- 知识库远程请求使用的 authenticatedFetch 令牌封装。
- 本地模型与用户自定义 API 配置。

## 验证

- npm run test:run -- react/test/community-models.test.js：2 项测试通过。
- 完整 React npm run build 通过：tsc -b 与 Vite 生产构建均成功，4658 个模块完成转换；专项 Vitest 5 项通过，仍有若干 chunk 大于 500 kB 的体积提示。
- 四份中英文翻译 JSON 均通过解析，源码扫描确认账号入口和模板分享入口已清理。
- 旧式进程管理测试脚本没有 Vitest 测试用例且引用不存在的安装器接口；联网下载脚本未运行。
- git diff --check 通过；route-tree.gen.ts 已恢复到 HEAD，无差异。

## 推送记录

- 将本次清理与回归测试作为无父提交的初始快照推送到 patdelphi/patjaaz 的 main。
- 提交：e4648bd22c67a5406ff169222cb1ae8fa5c09953。
- 远端 main 无旧提交历史，根目录 LICENSE 不存在。
- 本地 main 未改写；route-tree.gen.ts 已在构建后恢复到 HEAD 基线。todo.md 和后续 TypeScript 修复未推送。

## 状态

代码清理、专项回归测试及快照推送已完成。

## React TypeScript 构建错误修复（已完成）

### 范围

- CanvasExcali.tsx：移除当前 Excalidraw 类型不支持的 gridColor 设置；将主题 CSS 类放到容器上，保持画布布局和深色样式。
- VideoElement.tsx：让 onClick 回调匹配组件声明的参数类型，保留现有点击行为。
- DialogContent.tsx：将 easing 数组标注为固定元组，保持动画时长和曲线。
- ErrorBoundary.tsx：按 unknown 安全读取错误名称、消息和堆栈。
- Editor.tsx：修复 curPath 未定义引用，使用现有 knowledgeID 提供错误上下文。
- index.ts：将失效的 ModelSelector 导出指向现有 ModelSelectorV2，保留公开导出名称。

### 阶段

1. [x] 仅修复以上 TypeScript 报错，不做无关重构。
2. [x] 运行 React npm run build、专项 Vitest 和 Vite 生产构建。
3. [x] 审阅差异，确认公开导出、画布样式和其他本地改动保持正确。

### 完成标准

- [x] React npm run build 的 TypeScript 阶段通过。
- [x] 专项 Vitest 与 Vite 生产构建通过。
- [x] ModelSelector 公开导出继续可用，画布主题样式保留。
- [x] route-tree.gen.ts 已恢复到 HEAD；本地其他待推送改动保持原状。

### 状态

修复已完成。专项 Vitest 5 项通过，React npm run build 通过；TypeScript 修复尚未提交或推送。
## Jaaz 任务状态与 ComfyUI 实时进度优化

### 范围
- 保证每次聊天提交都有稳定的 session_id，并显示即时任务状态和运行时长。
- 让 /api/chat 快速确认接收，由后台任务执行完整 LangGraph/ComfyUI 流程。
- 复用现有 ComfyUI WebSocket 事件，在聊天界面显示排队、节点和百分比进度。
- 处理请求失败、任务完成/失败/取消及页面重连后的状态恢复。
- 添加不调用外部 LLM/ComfyUI 的回归测试；保留现有工作树改动。

### 阶段
1. [x] 补会话 ID 与 HTTP 错误回归测试。
2. [x] 将聊天任务改为快速确认和后台执行，维护任务状态快照。
3. [x] 接入状态查询/Socket.IO 进度恢复，改进状态、计时和错误提示。
4. [x] 运行后端专项测试、前端专项测试和生产构建，检查 diff 并保留 route-tree.gen.ts 现有差异。
5. [x] 重启 Jaaz 前后端并验证本地 HTTP 与状态 API 就绪；公网域名未请求验证。

### 完成标准
- 空 session_id 不会提交；前端请求失败时明确提示并清除 pending。
- /api/chat 在任务启动后快速返回；长工作流继续后台执行。
- ComfyUI 排队/节点/百分比信息能按当前 session 显示；刷新或断线重连时可恢复活跃任务状态。
- 完成、失败、取消都会结束运行提示。
- 专项测试和生产构建通过；既有未提交差异未被覆盖。

### 执行授权
用户已回复“执行”，按以上范围实施。

### 执行结果
- 后端专项 unittest 6 项和前端定向 Vitest 5 项通过；React TypeScript/Vite 生产构建通过。
- 全量 Vitest 被 Electron ComfyUI 安装器集成测试错误阻断；后端虚拟环境未安装 pytest，已用内置 unittest 执行目标测试。
- route-tree.gen.ts 已按构建前 SHA256 恢复；代码未提交或推送。
- 前后端已重启；57988/5174 主页与 `/api/chat/status/restart-probe` 均 HTTP 200，cloudflared 未重启。公网域名未请求验证。

## Jaaz 卡在 Thinking 的复查与修复

### 根因
- Socket.IO 客户端断开后，聊天任务可能已在 ComfyUI 完成；旧逻辑移除了任务状态快照，前端轮询无法得知终态，因而持续显示 Thinking。
- 图片结果已保存到画布数据库，但画布只依赖实时 ImageGenerated 事件更新内存场景；断线期间错过事件后看不到图片。
- 相同 session_id 的聊天重试会再次创建会话记录，触发 SQLite 主键冲突并返回 500。

### 修复与验证
- [x] 同一会话只允许一个后台任务；会话记录创建改为幂等。
- [x] 保留有限数量的任务终态快照；前端恢复保存的聊天结果，并从画布存储补同步缺失图片。
- [x] 增加空 fileId 防护，修复画布恢复代码的 TypeScript 类型错误。
- [x] 后端专项 unittest 3 项通过，前端定向 Vitest 6 项通过，Python 语法检查通过。
- [x] React TypeScript/Vite 生产构建通过，转换 4659 个模块；route-tree.gen.ts SHA256 未改变。

### 重启复查
- [x] 用户确认后重启 Jaaz 前后端，后端监听 57988，前端监听 5174。
- [x] 前后端主页返回 HTTP 200；状态接口返回 `{"known":false,"active":false}`，确认新代码已加载。
- [ ] 未提交新的 ComfyUI 生成任务；实时进度、终态回填和画布同步仍需真实任务复验。

## Jaaz write_plan 卡片 steps 类型异常

### 修复
- [x] 在 `WritePlanToolCall` 中使用安全解析器读取模型的 `steps` 参数；非数组时显示空列表，过滤缺少标题或字段类型错误的步骤。
- [x] 为有效数组、非数组结构、畸形条目和非法 JSON 增加回归用例。

### 验证
- [x] 新增测试 3 项通过；聊天进度/API 与参数解析定向测试合计 9 项通过。
- [x] React TypeScript/Vite 生产构建通过，转换 4660 个模块；route-tree.gen.ts SHA256 保持不变。
- [x] 本地后端提供新版百分比页面 bundle，静态资源 HTTP 200，代码已包含数组校验。
- [ ] 用户刷新浏览器后确认错误页消失。

## Jaaz write_plan 实际聊天烟测

- [x] 使用已配置的 DashScope `qwen3.7-plus` 发送一次只规划的聊天请求；API 接收成功，状态最终为 `completed`。
- [x] 会话历史包含 user/assistant/tool/assistant 共 4 条消息，触发 1 次 `write_plan`，`steps` 为 2 项数组，无任务错误。
- [x] React 组件渲染测试覆盖 `steps` 为字符串和对象时不崩溃。
- [x] 未传入图像工具、未调用 ComfyUI、未改动画布。
- 测试会话 ID：`codex-writeplan-smoke-20261123151210-cd0e1b0a`。

## ComfyUI MOSS 完整端到端测试

### 执行结果
- [x] 通过 Jaaz `/api/chat` 使用 `text2image_MOSS` 真实调用 ComfyUI，DashScope `qwen3.7-plus` 负责规划和工具选择。
- [x] 任务状态接口连续返回 ComfyUI 节点进度：`TextGenerate 1%`、`K采样器 4%` 至 `100%`、媒体回填和 `Task completed`。
- [x] 聊天任务终态 `completed`，无错误；历史包含 8 条消息和 3 条工具结果。
- [x] 独立测试画布 `Codex ComfyUI E2E 20261123` 写入 1 个有效图片元素和 1 个图片文件。
- [x] ComfyUI 输出 `H:\我的云端硬盘\comfyui\output\moss\moss_image_t2i_00106_.png`，2048×2048，6,672,234 字节。
- [x] Jaaz 图片接口 `/api/file/EA3rE9KfTE.png` 返回 HTTP 200，`image/png`，2048×2048，6,546,749 字节。

### 测试记录
- 会话 ID：`codex-comfyui-e2e-session-d44e8c9fd43a4d32baccb11532c8da75`。
- 测试画布 ID：`codex-comfyui-e2e-f3f32614875c4cc99bb361c1760726e9`。
- 只启用 `text2image_MOSS`；未使用输入图像或其他工作流。

## Jaaz 代码审查修复计划（2026-11-23）

### 范围
- 修复画布保存成功误报和失败不可见问题。
- 修复 Electron 后端启动无限等待，以及开发环境端口选择与前端代理不一致。
- 修正 CI 架构参数和 PR 发布行为，修复前端启动脚本与过时的中文开发说明。
- 暂缓匿名隧道的 API 安全改造，等待用户选择访问控制方式；不擅自改变既有匿名访问要求。

### 阶段
1. [x] 检查 Jaaz 前后端监听端口和进程；5174、57988、57989 均无监听，无需停止进程。
2. [ ] 画布保存：检查数据库更新行数；保存错误显示给用户；保存失败时不把旧画布伪装成最新结果。
3. [ ] 启动与开发连接：启动失败/超时给出可见错误；开发模式固定使用与 Vite、Socket.IO 相同的后端端口。
4. [ ] 工程化：CI 构建明确传入架构，PR 不发布；修复 `start:frontend`；同步中文开发文档。
5. [ ] 检查 diff、记录未完成项；本次不提交或推送。

### 完成标准
- 画布保存 API 不会在 0 行更新时返回成功；失败能显示原因，切换画布不会静默丢弃未保存状态。
- 后端启动失败后有限时间内显示诊断信息；开发模式前端 API 与 Socket.IO 指向同一后端实例。
- CI 的架构产物标签与实际构建参数一致，PR 构建不触发 GitHub 发布。
- 文档脚本与仓库实际目录结构一致；所有修改通过 diff 审查。

### 待用户决策
- Jaaz API 暴露了配置和本机文件操作。匿名公网访问的保护策略待用户选择；当前计划不改变隧道访问模式。
### 执行结果补记（2026-11-23）

- 已修复画布保存行数校验、保存错误提示和重开前等待保存；已修复 Electron 启动等待/端口处理、CI 参数与前端启动脚本，并更新中文开发说明。
- 按用户选择加入 `.env` 单一登录码，HTTP API 与 Socket.IO 连接均校验登录会话；本机访问码文件由 `.gitignore` 忽略。
- TypeScript 检查通过；Vite 生产构建通过（4665 个模块，输出到临时目录）；前端定向测试 12 项和登录服务测试 2 项通过；Electron JS 与 Python 语法检查通过。
- Python 画布数据库测试因环境缺少 `aiosqlite` 未运行，未安装依赖。`git diff --check` 报告一个既有 `CanvasPopbarContainer.tsx` 尾随空格，本轮未改该行。
- 检查时 Jaaz 前后端均未运行，所以无需停止；本轮未启动/重启服务，未提交/推送。
### Python 环境修复与本地整体测试（2026-11-23）

- `aiosqlite 0.22.1` 已安装到当前 Python 3.13 用户环境；项目 `server/.venv` 原先也已安装该版本。系统 Python 缺少 `aiofiles`、`langchain_core` 等运行依赖，因此本轮服务和 Python 测试使用项目虚拟环境。
- 项目虚拟环境 Python 单元测试 10/10 通过；React 全量测试 11 个文件、36 项通过；TypeScript 检查通过。
- 首次根目录 Vitest 全量测试误执行 Electron ComfyUI 安装器脚本，该脚本含真实网络下载/用户目录检查并造成 Vitest IPC 错误。已把默认 Vitest 收窄到 `react/test`，标准 `npm run test:run` 通过；未重复运行外部下载测试。
- 本地 HTTP 联调验证前端/API 200、未登录业务 API 401、错误访问码 401、正确访问码登录 200、Cookie 含 HttpOnly 与 SameSite=Strict、授权 API 200、缺失画布保存 404；Socket.IO 未登录拒绝、登录后可连接。
- 前端 `http://localhost:5174/` 与后端 `http://127.0.0.1:57988/` 当前返回 HTTP 200。服务保持运行。
- 本轮未提交 ComfyUI 生图任务或调用外部模型 API；未提交/推送 Git。
### Electron 启动适配补记（2026-11-23）

- 开发模式改为请求公开的 `/api/auth/status` 识别已启用登录码的 Jaaz 后端，避免受保护的设置 API 返回 401 后误判端口。
- 开发模式检测到 `server/.venv` 时优先使用其中的 Python；当前环境的虚拟环境路径存在。
- `node --check electron/main.js` 通过；当前服务的鉴权状态接口返回启用，已确认新识别条件匹配。
- 修改后再次运行标准 `npm run test:run`：11 个 React 测试文件、36 项全部通过；前后端仍在运行且 HTTP 200。
## M0 加固 + M1 画布快速改进（2026-11-24 已完成代码与自动测试）

依据：`Docs/04-Jaaz AIGC无限画布深度分析与规划.md` 第 3、4、7.4、9 节及 `Docs/06-Jaaz AIGC无限画布详细技术设计.md`。本轮不做去云端清理、ComfyUI 能力层和 pi Agent（分别属于 M1 主体与 M2）。

### 范围

- 安全 P0：路径穿越、任意删除、SSRF、嵌入放行、上传限制、Socket 跨域、`comfy_dynamic` 文件路径校验、`GET /api/config` Key 掩码、Electron 更新与脚本安全。
- 数据一致性：画布锁统一（含 `comfy_dynamic`）、缩略图保留、建画布顺序、删除级联、SQLite WAL 与外键、`done` 只发一次。
- 已知 bug：会话列表 500、`list_tools` KeyError、硬编码 localhost 链接、`comfyui_execution` 健壮性（`typer.Exit`、状态码校验、WS 超时与关闭、`on_status`、动态节点标题、输出键与种子保留）、路由吞 `HTTPException`、`onChange` 监听泄漏、Chat 事件订阅、`SocketProvider` 与 Vite `/socket.io` 代理、`CanvasTextBackground` 版本号递增、画布加载失败无提示。
- 鉴权补强：登录限流、访问码强度、签名会话令牌、Socket 随登出/过期断开、前端统一 401、安全响应头。
- 画布快速改进：线宽扩展（E2）、粗箭头头部缩放与 `getCanvasPadding` / 虚线缩放补丁（E1①）、闭合多边形块箭头（E1②）、工具栏补全（E3）、撤销/重做与缩放栏（E4）、CSS 隐藏改配置（E14）。

### 阶段

1. [x] 安全 P0
   - [x] 新增 `safe_join()`，`workspace.py` 的读/写/建/改名/删除全部限定在工作区根目录；`delete_file` 不再接受绝对路径。
   - [x] 本机文件浏览类接口（`browse_filesystem`、`serve_file`、`get_media_files`、`get_file_info`、`open_folder_in_explorer`）增加允许根目录配置，默认用户目录与 ComfyUI output。
   - [x] `/api/file/{file_id}` 校验文件名格式并检查 realpath 位于 `FILES_DIR`。
   - [x] `comfy_dynamic.py` 读取输入图片/媒体文件改用 `safe_join(FILES_DIR, filename)` 校验，缺失或非法直接报错，禁止静默放行。
   - [x] `comfyui/proxy`、`comfyui/object_info` 只使用配置中的 ComfyUI 地址，忽略前端传入的 URL。
   - [x] `GET /api/config` 对 API Key 做掩码返回；保存配置时保留未改动的掩码占位符不覆盖原密钥。
   - [x] `validateEmbeddable` 只放行 `/api/file/` 同源地址。
   - [x] 上传接口限制字节数、`Image.MAX_IMAGE_PIXELS`、MIME 白名单。
   - [x] Socket.IO `cors_allowed_origins` 限定为前端源。
   - [x] Electron 移除指向上游的 `autoUpdater` 逻辑，恢复 `webSecurity: true`（移除 `allowRunningInsecureContent`）；`ipcHandlers.js` 安装/卸载事件从字符串拼接 `executeJavaScript` 改为 `webContents.send`。
2. [x] 数据一致性
   - [x] 图片、视频与 `comfy_dynamic.py` 写画布共用同一个 `canvas_lock_manager`。
   - [x] `save_canvas_data` 未传缩略图时保留原值。
   - [x] `/api/canvas/create` 先插入画布再启动聊天任务。
   - [x] 删除画布时在同一事务内删除会话与消息（文件暂不删）。
   - [x] SQLite 开启 WAL 与 `foreign_keys=ON`（`busy_timeout=5000`）；多步写入使用事务。
   - [x] `done` 事件只由 `chat_service` 发送一次。
3. [x] 已知 bug
   - [x] 修复 `/api/list_chat_sessions` 缺参数。
   - [x] `list_tools` 对缺失 provider 配置使用 `.get()`。
   - [x] 工具返回值、上传接口的图片链接改为相对路径 `/api/file/...`。
   - [x] 修复 `comfyui_execution.py` 健壮性：用业务异常替代 `typer.Exit(code=1)`；`queue()`/`upload_image()` 补 `raise_for_status()`；`watch_execution()` 加超时并在 `finally` 关闭 WS（断线降级轮询 `/history`）；修复 `on_status` 过滤/`KeyError`/`None`；`get_node_title()` 用 `.get()` 兼容动态子图节点；输出提取覆盖 `images`/`gifs`/`videos`/`audio`。
   - [x] 修复 `comfy_dynamic.py` 无条件覆写用户显式传入 `seed` 的问题，并补充识别 `noise_seed`。
   - [x] 修复 `tool_confirmation.py`、`workspace.py`、`settings.py` 中 `except Exception` 吞掉内部 `HTTPException` 变成 500 的问题。
   - [x] `vite.config.ts` 增加 `/socket.io` WebSocket 代理；修复 `SocketProvider` 开发模式写死 `localhost:57988` 及在异步函数内返回清理函数的问题。
   - [x] `pop-bar/index.tsx`、`CanvasToolMenu.tsx`、`CanvasViewMenu.tsx` 的 `onChange` 订阅移入 `useEffect` 并在清理时注销。
   - [x] `Chat.tsx` 事件订阅只绑定一次（ref 保存最新回调）；去重逻辑移入 reducer，`setPending` 移出 `produce`。
   - [x] 抽取统一场景修改 helper `mutateSceneElements`（自动递增 `version`、`versionNonce`、`updated`），同步修复 `CanvasTextBackground.tsx`。
   - [x] 画布加载失败显示错误与重试按钮。
4. [x] 鉴权补强
   - [x] 登录失败按来源计数，5 次失败锁定 15 分钟；`X-Forwarded-For` 仅在请求来自本机代理时采信。
   - [x] 启动时访问码少于 16 个字符拒绝启动并提示。
   - [x] 会话改为 HMAC 签名令牌（secret 由访问码 + `user_data` 随机盐派生），后端重启不掉线，更换访问码后旧会话失效。
   - [x] 记录 Socket `sid → 会话`；登出时断开对应连接，定时断开过期连接。
   - [x] 前端封装统一请求函数，收到 401 时切回 AuthGate。
   - [x] 页面响应增加 `X-Frame-Options: DENY` 与基础 CSP。
5. [x] 画布快速改进
   - [x] E2：选中箭头/线条/形状时浮动条提供线宽档位 1、2、4、6、8、12、16、24 与自定义输入，经 `mutateSceneElements` 写入。
   - [x] E1①：整合为统一补丁脚本 `react/scripts/patch-excalidraw.mjs`，同步修补 `getArrowheadPoints`（箭头头部等比缩放 + 开放箭头半角微调）、`getCanvasPadding`（防 `20px` 离屏裁剪）与 `getDashArrayDashed`/`getDashArrayDotted`（粗虚线缩放）；画布与 SVG 导出一致。
   - [x] E1②：块箭头工具（直箭头、双向、弯箭头等），闭合 `line` 多边形（`roundness: null`、`roughness: 0`）+ `customData.kind = 'block-arrow'`，可改填充色、描边、头宽、尾宽，缩放时按参数重算顶点。
   - [x] E3：工具栏增加菱形、Frame、橡皮擦、激光笔、块箭头，按组折叠。
   - [x] E4：底部栏提供撤销、重做、缩放百分比、适配画布。
   - [x] E14：能用 `UIOptions` 关闭的原生界面改为配置关闭，其余隐藏规则集中到一个样式块并注明原因。
6. [x] 验证与收尾：检查 diff；更新 `Docs/` 规划文档状态；不提交、不推送。

### 完成标准

- 后端测试（`server/.venv/Scripts/python.exe -X dev -m unittest discover -s tests -v`，注明当前 `server/.venv` 未装 `pytest`）覆盖全量同步与 `IsolatedAsyncioTestCase` 异步用例：`safe_join` 穿越用例、`comfy_dynamic` 路径校验与种子保留、`/api/file` 非法文件名、ComfyUI 代理拒绝外部 URL、`GET /api/config` Key 掩码、路由 404 不被吞成 500、上传超限、缩略图保留、删除级联、画布锁串行、登录限流、签名令牌过期与换码失效、登出/过期 Socket 断连。
- 前端测试（Windows PowerShell 下用 `npm.cmd run test:run`）新增并通过：`onChange` 订阅清理、`mutateSceneElements` 版本号递增、箭头尺寸缩放与 padding 计算、块箭头顶点生成、401 处理；`react` 下 `npm.cmd run build` 通过。
- 补丁脚本 `patch-excalidraw.mjs` 锚点找不到或版本不匹配时让安装直接报错，并有 Vitest 单测覆盖。
- 手工验证：生成图片期间连续编辑画布 10 次无元素丢失；首页缩略图在工具写入后仍存在；线宽 16 的箭头头部等比放大且四边不被裁剪、虚线不粘连；块箭头可拉伸并导出 PNG/SVG；界面可撤销/重做；错误访问码 5 次后被锁；后端重启后已登录浏览器无需重新登录。
- 未执行项和遗留问题记录在本节末尾。

### 已确认决策

- ~~Agent 引擎采用 earendil-works/pi，新增 Node Agent 服务（M2 实施）。~~
- ~~Agent 服务目录为仓库根目录 `agent/`，与前端共享 `packages/shared`（事件与工具 schema）。~~
  - **2026-11-25 决策变更**：忽略/取消更换 `pi` Agent 引擎任务，保留现有 Python LangGraph 分组智能体架构，将画布编排工具、指向式标注与长会话压缩直接在现有 Python 服务上迭代。
- 画布继续使用 Excalidraw，按 7.4 与 `Docs/06-Jaaz AIGC无限画布详细技术设计.md` 第 4 节增强。

### 执行结果与未执行项（2026-11-24）

- 自动化验证通过：
  - Python 语法检查（`py_compile` 全部 25 个受影响后端模块）：退出码 0。
  - 后端全量测试（`server/.venv/Scripts/python.exe -X dev -m unittest discover -s tests -v`）：共 9 个测试文件、48 个同步与 `IsolatedAsyncioTestCase` 异步用例全部通过（1.097s，含原有 3 个异步历史测试与阶段 2–4 新增的 11 个异步运行时测试）。
  - Electron 语法检查（`node --check electron/main.js electron/ipcHandlers.js electron/preload.js`）及 Excalidraw 0.18.1 补丁脚本 `react/scripts/patch-excalidraw.mjs` 幂等执行通过。
  - 前端单元测试（`npm.cmd run test:run`）：17 个测试文件、49 个用例全部通过。
  - 前端类型与构建（`react` 下 `npm.cmd run build`，`tsc -b && vite build`）：成功（17.91s），`git diff --check` 退出码 0。
- 未执行项：
  - 浏览器与真实 ComfyUI 运行态手工验证：并发编辑不丢失元素、线宽 16 箭头视觉与 PNG/SVG 导出不裁剪、块箭头交互拉伸、错误访问码 5 次锁定、重启后免重登待人工交互验证。
  - 本轮 M0 + M1 代码改动保留在工作区，尚未执行 `git add` / `git commit` / `git push`。

---

## M1 主体：去云端 + ComfyUI 外部文件组工作流与多实例能力层 + 三协议模型（2026-11-24 已完成待确认提交）

依据：`Docs/04-Jaaz AIGC无限画布深度分析与规划.md` 第 2.3、7.1、7.2、7.10、9 节及 `Docs/06-Jaaz AIGC无限画布详细技术设计.md` 第 1.2、3 节（含新增 3.6 外部文件组工作流包规范）。本轮完成后，不配置任何云端 Key，仅用本地/线上 ComfyUI + 任一开放 LLM 即可完成生图、编辑、视频/TTS 与工具开关管理（注：M2 `pi` Agent 替换已于 2026-11-25 取消）。

### 范围

- 去 Jaaz 云端清理：移除 13 个 `*_jaaz` 工具、`jaaz_provider`/`jaaz_service`/`magic_service`/`knowledge_service`/`mcp`/`OpenAIAgents_service`，移除前端 Magic/Knowledge/AgentStudio 入口、PostHog 上报、`ModelSelectorV2` 冗余实现与 `jaaz.app` 云端常量；下线 Volces/Replicate/Wavespeed 等直连第三方媒体默认注册，清理 `react/package.json` 中的 `tldraw` 与 `posthog-js`。
- SQLite v4 迁移（迁移前自动备份 `localmanus.db`）：创建 `comfy_instances` 与 `jobs` 表，扩展 `comfy_workflows`（`display_name`、`capability`、`output_kind`、`enabled`、`instance_id`、`source_mode`、`source_path`、`seed_strategy`、`schema_version`、`checksum`），兼容保留历史 DB 工作流（`text2image_MOSS`、`ImageEdit_MOSS`）并默认启用。
- ComfyUI 多实例与通信加固（K1–K2、K4–K5）：`urlsplit` 保留子路径前缀解析 HTTP/WS，支持 Bearer/Basic/自定义 Header 鉴权（掩码存储返回），恢复 `HttpClient` 连接池，定期/手动健康检查，上传 `sha256` 去重缓存，流式视频/音频写入，任务取消联动调用 ComfyUI `/queue` 删除与 `/interrupt`。
- 项目内指定目录成对文件 ComfyUI 工作流与管理端开关（K3 升级）：
  - 固定项目内目录 `<repo_root>/workflows/`，支持成对文件：`<repo_root>/workflows/<dir>/{workflow.api.json, jaaz.workflow.json}` 与平铺成对 `<repo_root>/workflows/{name.api.json, name.jaaz.json}`；
  - 导入与扫描时严格校验：拦截 ComfyUI UI 画布 JSON，逐项验证 `inputs[].node_id` 与 `node_input_name` 在 API JSON 中的存在性；
  - 管理端支持：导入成对文件组（落盘到 `workflows/`）、一键扫描项目内 `workflows/` 目录同步、上传单个 API JSON 自动生成 `jaaz.workflow.json` 模板草稿、一键导出已有工作流为双文件组、查看参数列表与节点校验状态、原地事务编辑（`PUT`）与一键开关（Switch）；关闭后立即从 `tool_service` 和 `/api/list_tools` 移除，不让 Agent 选用；
  - 废除旧版 `ComfyuiWorkflowSetting.tsx`“编辑先删再建”危险流程与复杂手工逐节点拼表弹窗。
- 统一 `CapabilityProvider` 接口与注册表（`server/services/capabilities/`）：定义 `Capability`、`AssetRef`、`ProgressUpdate`、`CancelToken`、`CapabilityProvider`、`CapabilityRegistry`，ComfyUI 作为默认实现，预留 TTS / ASR / 音乐等外部 HTTP API Provider 基类。
- 开放文本模型三协议支持（L1–L2，方案 A 零新增依赖）：支持 `openai`、`anthropic`、`google`、`openai-compatible` 四类协议配置、模型能力标记（`vision`、`tools`、`thinking`、`context_length`）与 `/api/settings/test_llm` 连通性测试（密钥脱敏）。

### 阶段

1. [x] 去 Jaaz 云端清理与冗余移除
   - [x] 移除 `server/tools/*_jaaz.py`、`jaaz_provider.py`、`jaaz_service.py`、`magic_service.py`、`knowledge_service.py`、`mcp.py`、`OpenAIAgents_service/` 及相关依赖路由（`chat_router` 的 `/magic*`、`settings.py` 的 `/knowledge/enabled`）；将 4 个 `*_replicate.py` 的 Pydantic Schema 内联移除断链依赖。
   - [x] 清理 `config_service.py` 中的 `jaaz` 默认提供商、`BASE_API_URL`、`_get_jaaz_url`（并在加载旧 `config.toml` 时自动跳过 `[jaaz]` 段）；清理 `tool_service.py` 中云端工具默认注册。
   - [x] 清理 `image_vide_creator_config.py` 与 `StreamProcessor.py` 中写死的 `*_jaaz` 工具引用。
   - [x] 清理前端 `Magic`（`api/magic.ts`、`ChatMagicGenerator`、`CanvasMagicGenerator`、`event.ts`）、`Knowledge`（`api/knowledge.ts`、`knowledge.tsx`）、`AgentStudio`（`routes/agent_studio.tsx`）、`api/auth.ts`、`constants.ts` 中的 `jaaz.app`/`BASE_API_URL`/`LOGO_URL`、`PostHogProvider`、`ModelSelectorV2`，清理 `react/package.json` 的 `tldraw` / `posthog-js` 并重新生成 `route-tree.gen.ts`。
2. [x] SQLite v4 迁移（自动备份）与 ComfyUI 多实例能力加固
   - [x] 实现迁移前自动备份 `localmanus.db`（含 `-wal`/`-shm`）到 `USER_DATA_DIR/backups/`，失败时自动回滚恢复（实测备份至 `server/user_data/backups/localmanus.db.bak-v3-20261124161442`）。
   - [x] 新增 `v4` 迁移：`comfy_instances` 表、`jobs` 表、幂等扩展 `comfy_workflows` 元数据与 `enabled`/`source_mode`/`source_path`/`checksum` 等列，保留既有 `text2image_MOSS` / `ImageEdit_MOSS` 并自动回填默认能力与启用状态。
   - [x] 提取 `comfy_instance_service.py`（保留子路径前缀的 HTTP/WS 解析、Bearer/Basic/自定义 Header、密钥掩码、`sha256` 上传去重缓存、恢复 `HttpClient` 连接池）。
   - [x] 实现多实例管理 CRUD、健康探测（`/system_stats`）与 `/api/cancel/{session_id}` 联动调用 ComfyUI `/queue` 删除与 `/interrupt`。
3. [x] 项目内 `workflows/` 成对文件 ComfyUI 工作流与管理端启停开关
   - [x] 新建 `<repo_root>/workflows/README.md`、`workflows/jaaz.workflow.schema.json`、`.agents/skills/import-comfyui-workflow/SKILL.md` 与 `server/scripts/workflow_cli.py`，形成完整外部 AI Agent 直接导入契约（`inspect` -> `validate` -> `install` / `enable` / `disable` / `export-all`）。
   - [x] 新建 `server/services/comfy_workflow_pack.py` 与 `server/services/comfy_workflow_ai_importer.py`：支持节点连线过滤与 `/object_info` 枚举融合摘要、由系统已配置 LLM 直接解析 API JSON 生成配置并在校验失败时自动二次纠错、`workflows/` 目录启动及页面刷新增量热同步。
   - [x] 新建 `server/routers/comfyui_router.py` 并更新 `main.py`、`db_service.py`、`tool_service.py`、`comfy_dynamic.py`、`root_router.py`、`image_router.py`：提供 `/workflows/inspect` 与 `/workflows/ai_import` 一键入库接口；`register_comfy_tools()` 只注册 `enabled = 1` 且按 `output_kind` 注册真实类型；关闭开关立即刷新 `tool_service` 使其对 Agent 不可见。
   - [x] 重构 `ComfyuiSetting.tsx` 与 `ComfyuiWorkflowSetting.tsx`（内置默认“AI 自动解析导入”Tab、成对文件导入、目录同步、单行参数/开关管理），新增 `react/src/lib/comfyWorkflowPack.ts`，更新 `ModelSelectorV3.tsx` 支持 `audio` 标签页。
4. [x] 统一 `CapabilityProvider` 抽象层与扩展注册表
   - [x] 新增 `server/services/capabilities/`：`base.py`（`Capability`、`AssetRef`、`ProgressUpdate`、`CancelToken`、`CapabilityProvider`、`HttpApiCapabilityProvider`）、`registry.py`（按 `capability` 与优先级路由及故障回退）、`comfyui_provider.py`（接入已启用的 ComfyUI 工作流调度）。
   - [x] 编写能力注册表、ComfyUI 禁用隔离、故障回退与外部 `TTS` 桩实现单元测试。
5. [x] 开放文本模型三协议支持（L1–L2，方案 A 零新增依赖）
   - [x] 扩展 `config_service.py` 与 `config_model.py`：支持 `protocol`（`openai`/`anthropic`/`google`/`openai-compatible`）、协议自动推断及模型能力标记（`vision`/`tools`/`thinking`/`context_length`）。
   - [x] 新建 `server/services/llm_adapters.py`：基于已装 `anthropic` 与 `httpx` 实现 `AnthropicNativeChatModel` 与 `GeminiNativeChatModel`（均完整支持 `bind_tools` 与 `create_react_agent`）、`create_chat_model` 路由及 `/api/settings/test_llm` 连通性测试（错误密钥脱敏）。
   - [x] 更新前端 `llmProtocol.ts`、`types.ts`、`AddProviderDialog.tsx`、`CommonSetting.tsx`、`AddModelsList.tsx` 支持协议切换、能力标签开关与一键测试连接。
6. [x] 全量验证与文档收尾
   - [x] 新增 `test_m1_cloud_cleanup.py`、`test_m1_comfy_packs.py`、`test_m1_capabilities_and_llm.py`、`test_m1_ai_workflow_import.py` 与 `react/test/comfy-workflow-pack.test.js`、`llm-protocol-config.test.js`。
   - [x] 后端 `py_compile`、`server/.venv/Scripts/python.exe -X dev -m unittest discover -s tests -v`、前端 `npm.cmd run test:run`、前端 `npm.cmd run build`、`git diff --check` 与文档 UTF-8 BOM + CRLF 检查通过。
   - [x] 更新 `Docs/06` 与 `todo.md` 执行状态，保持 UTF-8 BOM + CRLF；未执行 git commit/push，等待用户审阅确认。

### 完成标准

- 未配置任何云端 Key，且仓库不含 `jaaz.app` 云端工具、`magic_service`、`knowledge_service` 与 `mcp`。
- 本地或外部目录的一组文件（`workflow.api.json` + `jaaz.workflow.json`）导入即用，缺失节点或错传 UI JSON 时给出明确中文报错，不会静默失败。
- 管理端对工作流切换启用/关闭开关后，`/api/list_tools` 与 Agent 工具集实时同步；关闭后的工作流不会被 Agent 选中。
- `CapabilityProvider` 注册表与多实例 `/interrupt` 取消链路均有自动化单元测试覆盖；OpenAI、Claude、Gemini、OpenAI-compatible 四类模型可配置、保存并经过测试验证。

### 已确认事项（2026-11-24）

1. **工作流文件组目录**：固定在项目内目录 `<repo_root>/workflows/`，兼容 `<dir>/{workflow.api.json, jaaz.workflow.json}` 与 `<name>.api.json + <name>.jaaz.json`；禁用工作流从 `tool_service`（Agent）和 `/api/list_tools` 同时隐藏。
2. **清理与迁移**：已批准删除废弃云端/Magic/Knowledge/MCP 文件、执行 SQLite v4 迁移（自动备份 `localmanus.db`）、从 `react/package.json` 移除未使用的 `tldraw` 和 `posthog-js`。
3. **阶段 5 接入方案**：选定方案 A（零新增 Python 依赖，使用已安装的 `anthropic` 与 `httpx` 实现原生 Claude / Gemini REST `BaseChatModel` 适配）。

---

## 画质参数修复 + 流水线闭环 + Stage C 工程治理与画布交互增强（2026-11-25 已完成，不含桌面端打包与换 Agent）

### 范围
- 优先修复 `text2image_minimax_h3` 等工作流出图过曝与参数调用问题，并在线上 ComfyUI 实测对比验证。
- 补齐上传 SHA-256 缓存过期自动重传（R-10）、音频元素落盘画布（C5）、PNG/SVG 画布导出合成视频封面帧及粘贴内联 Base64 图片自动外置（C2）。
- 完成前端 Vite 分包（R-21）、开启 `noUnusedLocals`/`noUnusedParameters`（R-22）、日志脱敏（R-18）、LLM `usage_metadata` 与客户端复用（R-11）、工作流 `mtime` 缓存（R-25）、系统提示词后端持久化（R-26）、本地假 ComfyUI 联调测试与单测提速（R-23/R-24）。
- 补齐画布顶部生成进度浮层（C4）、悬浮栏 AI 快捷动作菜单（E9）、自动递增序号标注（E5）及 `Docs/08~11` 工程文档（R-28）。
- 按用户要求排除桌面端打包安装测试与 Agent 引擎替换。

### 完成与验证记录
- [x] 出图画质修复与线上实测：`text2image_minimax_h3` 的 `KSampler` `cfg` 由 `8` 修正为 `1`（`steps: 8`），`megapixels` 默认值调至 `2.0`、`enable_prompt_enhancer` 默认设为 `false`；线上 Colab ComfyUI 同题词重新生成 `BmohWDeQnC.png`，高光自然、发丝与织物细节清晰。
- [x] 批次一流水线闭环：上传缓存失效单次自动重传、音频卡片写入画布与广播、PNG/SVG 导出视频帧合成、粘贴 `data:image/*` 自动上传外置。
- [x] 批次二工程治理：前端 `tsc -b && vite build` 零报错通过（入口包 327.75 kB），后端全量单测提速至 9 秒内并新增本地假 ComfyUI HTTP+WS 测试。
- [x] 批次三画布交互与文档：完成 `CanvasGenerationOverlay`、`CanvasQuickActions`、`calloutBadge` 及 `Docs/08-requirements.md`、`Docs/09-api.md`、`Docs/10-deployment.md`、`Docs/11-changelog.md`（全部 UTF-8 BOM + CRLF）。
---

## 14 套工作流全量审查、SenseNova U1.6 接入与 9 轮全流程自动画布实测（2026-11-25 已完成）

### 完成与验证记录
- [x] 全量工作流参数与节点校准：逐一审查修正 12 套既有工作流（MiniMax H3 图像切换 `qwen3vl_32b_minimax_h3_nvfp4_awq` 适配 24GB 显存、`4.0 MP`、`cfg=1`、多图编辑锁定 `enable_prompt_enhancer=false` 保护 `<Picture N>` 标签；视频工作流统一 `0.98 MP` 768p、清理失效预览节点并将 `SaveVideo` 输出前缀统一归入 `video/` 目录）。
- [x] SenseNova U1.6 双工作流导入与种子兼容：导入并启用 `text2image_sensenova_u16` 与 `image_edit_sensenova_u16`，在 `comfy_dynamic.py` 支持独立 `PrimitiveInt`（标题含 `seed`/`种子`）随机种子注入。
- [x] 视频输入上传与反向代理执行加固：将 `video`/`audio` 输入文件上传至 ComfyUI `input/` 根目录以通过 `LoadVideo`/`LoadAudio` 的 `COMBO` 校验；为 `WorkflowExecution.connect()` 增加 3 次握手重连与 `/history` 降级轮询；启用 `video_upscale_seedvr2_3b`。
- [x] 工作流完整手册与单画布 9 轮复杂实测：编写 `Docs/12-ComfyUI工作流完整使用说明.md`；在单画布 `auto-flow-tea-film-2026`（会话 `sess-tea-film-2026`）通过 `chat_service` 串行跑通文生图、单图改字改物、双图融合改图、首帧有声出视频、双参考重拍改视频（含中文台词）、SeedVR2 裁剪 + 1.5× 2K 超分精修与制片清单复盘，129 个画布元素零重叠，后端 109 项单测全部通过。

---

## 后续待优化与功能演进计划（2026-11-25 更新，忽略更换 Agent 引擎）

> 范围约束：不更换现有 Python LangGraph 智能体引擎，不做桌面端安装包实测；所有后续能力均在现有 FastAPI + LangGraph + Excalidraw 架构上渐进演进。

### 阶段 P1：实测暴露的执行链路与消息持久化加固（高优先级）
- [x] **子图工具调用即时落库**：改造 `StreamProcessor.py`，在工具节点返回成功结果时即时幂等写入 `chat_messages`，避免 ComfyUI 已出图落盘后因收尾总结请求偶发 `429` 或网络抖动导致对话侧缺失工具记录。
- [x] **ComfyUI 中间预览输出过滤**：在 `comfyui_execution.py` / `comfy_dynamic.py` / `job_recovery.py` 支持按 `jaaz.workflow.json` 的 `outputs` 节点白名单或终端保存节点类型（`SaveImage`、`SaveVideo`、`SaveAudio`、`VHS_VideoCombine`）过滤输出，剔除 `LoadVideo` / `LoadImage` 等输入节点的中间预览文件。
- [x] **实例跨模型家族显存自动释放**：在 `comfy_instance_service` 记录实例最近一次执行的工作流模型家族，跨大模型家族（如 SenseNova ↔ MiniMax H3 ↔ SeedVR2）切换前按配置自动触发 `/api/free`，降低 24GB 显存环境冷切换时的内存交换耗时。

### 阶段 P2：Python Agent 原生画布编排工具与上下文精简（原 M2 有价值项迁入）
- [x] **画布图形与排版工具集（A2）**：在后端新增 `canvas_arrange_elements` / `canvas_connect_and_badge`（`server/tools/canvas_tools.py`）并经 Socket.IO `canvas_elements_updated` 同步前端，支持通过自然语言让 LLM 直接创建 `Frame` 分镜泳道、写入分镜文字框、重排缩放媒体卡片及绘制带标签流转箭头与序号角标。
- [x] **序号角标指向式局部指令（A3）**：在 `canvas_context.py` 识别画布 `callout-badge`（`①`、`②`…）所贴附的底层图像/视频元素与九宫格相对方位及百分比坐标，自动注入 `<canvas_scene_context>`。
- [x] **长会话历史滑窗与参数折叠（A9）**：新增 `context_compactor.py` 并在 `agent_service.py` 接入，当单会话超过设定窗口时自动折叠早期 `write_plan` 与冗长工具提示词参数，保留 `tool_call_id` 配对与 `/api/file/...` 引用。

### 阶段 P3：画布深度交互、资产血缘谱系与大画布性能（M3–M4 进阶）
- [x] **局部重绘涂抹遮罩与对比导出（G2 / E8 / X1）**：新增 `CanvasImageTools.tsx` 与 `canvasFrameExport.ts`，提供双层画布画笔涂抹遮罩（Mask）导出透明通道 PNG 对接 Inpaint 工作流、改图前后滑块对比（Before/After）、图片水平翻转/圆角切换及按 `Frame` 批量多格式倍率导出（PNG/JPG/WebP/PDF）。
- [x] **生成血缘谱系与一键重抽（C9）**：在 `comfy_dynamic.py` 向图像/视频元素 `customData.jaazLineage` 写入生成工作流、Prompt、Seed 与上游输入 `file_id`，悬浮栏支持查看生成参数、同工作流换种子一键重抽及选中高亮上游父资产。
- [x] **增量同步、图层快照与大画布减负（C1 / C7 / C10 / C11）**：新增 `canvas_ops_service.py`、`/api/canvas/{id}/ops` 与 `/snapshots*`、`canvasIncrementalSync.ts`、`CanvasLayersAndSnapshotsDrawer.tsx`，支持元素级 `op` 增量同步、图层显隐/锁定/排序面板、SQLite 事务历史快照回退，并在 `VideoElement.tsx` 接入 `content-visibility: auto`、`contentvisibilityautostatechange` 与 `IntersectionObserver` 实现视口外视频自动暂停。

### 阶段 P4：资产库、配音成片合成与大文件拆分治理（M4–M5 & Stage C 尾项）
- [x] **跨画布资产与形状模板侧边栏（M1 / E10）**：新增 `studio_router.py`（`/api/studio/assets`、`/api/studio/templates`）与 `CanvasStudioDrawer.tsx`，支持按关键词与媒体类型跨画布检索资产一键入画及插入三镜分镜框组合模板。
- [x] **脚本卡 TTS 配音与 `ffmpeg` 分镜合成（V3 / V4）**：新增 `video_compose_service.py`、`/api/studio/tts` 与 `/api/studio/compose_video`，在悬浮快捷菜单增加一键配音入口，支持多镜头视频拼接、旁白混音与 SRT 软字幕压制。
- [x] **表格变量批量生成与流程模板化（W1 / W2）**：实现 CSV/多行变量解析展开接口 `/api/studio/batch_expand` 与工作台批量派发界面。
- [x] **后端超长模块拆分与统一日志（R-17 / R-19）**：将 `comfy_workflow_pack.py`、`db_service.py`、`comfyui_router.py`、`llm_adapters.py` 拆分为 10 个职责清晰且均不超过 600 行的模块（100% 保留公开导出），并将核心服务中的裸 `print` 收敛至 `get_sanitized_logger`。

### 完成标准与验证结果（2026-11-25 已完成代码与全量自动测试）
- [x] 阶段 P1–P4 新增 4 个后端单测文件（`test_stage_p1_pipeline_hardening.py`、`test_stage_p2_canvas_tools_and_context.py`、`test_stage_p3_ops_snapshots_lineage.py`、`test_stage_p4_studio_compose_and_splits.py`）与 2 个前端单测文件（`stage-p3-incremental-pdf.test.js`、`stage-p4-studio-and-layers.test.js`）。
- [x] 后端全量单测：122 项测试全部通过（7.75s）；前端全量 Vitest：24 个测试文件、70 项测试全部通过（1.08s）；前端 `tsc -b && vite build`（4666 个模块，17.50s）与 `git diff --check` 零报错通过。
- [x] 已按用户指令重启 `57988` 后端进程加载 P1–P4 及内置 FFmpeg 新模块；本轮代码与文档改动尚未执行 `git commit` / `git push`，等待用户确认。

---

## 服务重启验收 + 项目内置 FFmpeg 自动剪辑拼接 + 1 分钟（4×15s）复杂短片全链路实测（2026-11-25 已完成）

### 范围与完成记录
1. [x] 将 `ffmpeg.exe` 与 `ffprobe.exe` 内置到项目 `server/bin/` 目录（摆脱操作系统 `PATH` 依赖，并在 `.gitignore` 忽略 `server/bin/*.exe` 避免超 100MB 阻塞 GitHub 推送），升级 `video_compose_service.py` 支持按秒裁剪截齐、原生立体声音轨串联、0.25 秒音画柔化转场与血缘记录，新增 `video_edit_and_stitch` 智能体工具并同步工作室面板。
2. [x] 重启 `57988` 服务并完成 6 项在线实测（内置 `server/bin/ffmpeg.exe` 探测、登录鉴权、画布增量 `/ops` 与快照回退、跨画布资产与模板检索、CSV 变量批量展开、在线 `/api/chat` 调用 `canvas_arrange_elements` 建框与工具消息即时落库）。
3. [x] 在画布 `film-1min-4x15s-2026`（`https://jaaz.patdelphi.xyz/canvas/film-1min-4x15s-2026`）完成《江南夜雨·一盏江湖》1 分钟（`4 × 15.0s`）四篇章五拍完整分镜排布，并串行生成 4 段完整 15 秒有声视频（`1n8wCYLbMD.mp4`、`7nlR5sICvj.mp4`、`l0YOL01b3x.mp4`、`9Tfcqv9T5t.mp4`，每段实测均为 `15.083s` / `362` 帧 @ `24fps` / `928×512` / `aac` 立体声）。
4. [x] 通过真实聊天让 Jaaz 智能体自动调用 `video_edit_and_stitch`，将 4 段分镜截齐为 `15.0s × 4` 并拼接生成 **`60.0` 秒整 1 分钟有声总成片** `composed_im_yC4Cbx-G.mp4`（耗时 `30.1s`），完成画布总装连线、血缘记录与声画抽帧核验。
5. [x] 新增 `file_mapping_service.py`（`GET /api/studio/file_mappings` + UTF-8 BOM + CRLF `file_mappings.csv` 自动双向记录 ComfyUI 与 `H:` 云盘文件）；在 Colab Tesla T4（15GB 显存）上完成 `6 × 10s` 分段 `SeedVR2 3B` `2×` 超分并由内置 `ffmpeg` 合流原 60s 立体声音轨产出 **`1856 × 1024` 全高清终版** `upscaled_x2_60s_master.mp4`（`97.66 MB`）。

---

## 阶段 P5：分钟级长片生产闭环与硬件自适应守护（2026-11-26 已完成）

### 范围与阶段
1. [x] **P5-1 长视频自动分块超分与断点续跑内置化**：按远端可用内存自动计算安全切片秒数，使用内置 `ffmpeg` 预切片并逐段调用 `SeedVR2` 超分落盘记录进度；支持远端断线后从已完成切片断点续跑，并自动无损合流原视频音轨写回画布。
2. [x] **P5-2 角色定妆锚定与视频抽帧接力串联工具**：新增内置 `ffmpeg` 视频关键帧/尾帧提取工具 `extract_video_frame` 并挂载画布血缘，支持分钟级多段视频自动抽尾帧接力 `image2video_first_frame` / `ref2video_dual` 锁定人物与服饰一致性。
3. [x] **P5-3 远端 GPU 规格自适应防呆与 Colab 换址热续跑**：在工作流执行前检测 `/system_stats` 显卡架构与显存/内存（如拦截 T4 `SM 7.5` 上的 `NVFP4` 大模型报错、自动约束 15 秒长视频安全 `megapixels`），并提供 Colab 新隧道地址一键热更新与挂起队列续跑接口。
4. [x] **P5-4 内置 `ffmpeg` 成片精装升级**：扩展 `video_edit_and_stitch` 支持 `loudnorm`（EBU R128）多段响度自动均衡、SRT 硬字幕画面烧录（自定义字号描边）及片头标题渐显与片尾黑场淡出。
5. [x] **P5-5 前端「云盘映射与存储清理」工作台面板**：在 `CanvasStudioDrawer` 新增云盘映射检索标签页、断点超分任务续跑/Colab 换址入口，以及未绑定任何画布的孤立临时切片扫描与显式二次确认清理功能。
