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
## M0 加固 + M1 画布快速改进（2026-11-24 规划，待确认后执行）

依据：`Docs/04-Jaaz AIGC无限画布深度分析与规划.md` 第 3、4、7.4、9 节及 `Docs/06-Jaaz AIGC无限画布详细技术设计.md`。本轮不做去云端清理、ComfyUI 能力层和 pi Agent（分别属于 M1 主体与 M2）。

### 范围

- 安全 P0：路径穿越、任意删除、SSRF、嵌入放行、上传限制、Socket 跨域、`comfy_dynamic` 文件路径校验、`GET /api/config` Key 掩码、Electron 更新与脚本安全。
- 数据一致性：画布锁统一（含 `comfy_dynamic`）、缩略图保留、建画布顺序、删除级联、SQLite WAL 与外键、`done` 只发一次。
- 已知 bug：会话列表 500、`list_tools` KeyError、硬编码 localhost 链接、`comfyui_execution` 健壮性（`typer.Exit`、状态码校验、WS 超时与关闭、`on_status`、动态节点标题、输出键与种子保留）、路由吞 `HTTPException`、`onChange` 监听泄漏、Chat 事件订阅、`SocketProvider` 与 Vite `/socket.io` 代理、`CanvasTextBackground` 版本号递增、画布加载失败无提示。
- 鉴权补强：登录限流、访问码强度、签名会话令牌、Socket 随登出/过期断开、前端统一 401、安全响应头。
- 画布快速改进：线宽扩展（E2）、粗箭头头部缩放与 `getCanvasPadding` / 虚线缩放补丁（E1①）、闭合多边形块箭头（E1②）、工具栏补全（E3）、撤销/重做与缩放栏（E4）、CSS 隐藏改配置（E14）。

### 阶段

1. [ ] 安全 P0
   - [ ] 新增 `safe_join()`，`workspace.py` 的读/写/建/改名/删除全部限定在工作区根目录；`delete_file` 不再接受绝对路径。
   - [ ] 本机文件浏览类接口（`browse_filesystem`、`serve_file`、`get_media_files`、`get_file_info`、`open_folder_in_explorer`）增加允许根目录配置，默认用户目录与 ComfyUI output。
   - [ ] `/api/file/{file_id}` 校验文件名格式并检查 realpath 位于 `FILES_DIR`。
   - [ ] `comfy_dynamic.py` 读取输入图片/媒体文件改用 `safe_join(FILES_DIR, filename)` 校验，缺失或非法直接报错，禁止静默放行。
   - [ ] `comfyui/proxy`、`comfyui/object_info` 只使用配置中的 ComfyUI 地址，忽略前端传入的 URL。
   - [ ] `GET /api/config` 对 API Key 做掩码返回；保存配置时保留未改动的掩码占位符不覆盖原密钥。
   - [ ] `validateEmbeddable` 只放行 `/api/file/` 同源地址。
   - [ ] 上传接口限制字节数、`Image.MAX_IMAGE_PIXELS`、MIME 白名单。
   - [ ] Socket.IO `cors_allowed_origins` 限定为前端源。
   - [ ] Electron 移除指向上游的 `autoUpdater` 逻辑，恢复 `webSecurity: true`（移除 `allowRunningInsecureContent`）；`ipcHandlers.js` 安装/卸载事件从字符串拼接 `executeJavaScript` 改为 `webContents.send`。
2. [ ] 数据一致性
   - [ ] 图片、视频与 `comfy_dynamic.py` 写画布共用同一个 `canvas_lock_manager`。
   - [ ] `save_canvas_data` 未传缩略图时保留原值。
   - [ ] `/api/canvas/create` 先插入画布再启动聊天任务。
   - [ ] 删除画布时在同一事务内删除会话与消息（文件暂不删）。
   - [ ] SQLite 开启 WAL 与 `foreign_keys=ON`（`busy_timeout=5000`）；多步写入使用事务。
   - [ ] `done` 事件只由 `chat_service` 发送一次。
3. [ ] 已知 bug
   - [ ] 修复 `/api/list_chat_sessions` 缺参数。
   - [ ] `list_tools` 对缺失 provider 配置使用 `.get()`。
   - [ ] 工具返回值、上传接口的图片链接改为相对路径 `/api/file/...`。
   - [ ] 修复 `comfyui_execution.py` 健壮性：用业务异常替代 `typer.Exit(code=1)`；`queue()`/`upload_image()` 补 `raise_for_status()`；`watch_execution()` 加超时并在 `finally` 关闭 WS（断线降级轮询 `/history`）；修复 `on_status` 过滤/`KeyError`/`None`；`get_node_title()` 用 `.get()` 兼容动态子图节点；输出提取覆盖 `images`/`gifs`/`videos`/`audio`。
   - [ ] 修复 `comfy_dynamic.py` 无条件覆写用户显式传入 `seed` 的问题，并补充识别 `noise_seed`。
   - [ ] 修复 `tool_confirmation.py`、`workspace.py`、`settings.py` 中 `except Exception` 吞掉内部 `HTTPException` 变成 500 的问题。
   - [ ] `vite.config.ts` 增加 `/socket.io` WebSocket 代理；修复 `SocketProvider` 开发模式写死 `localhost:57988` 及在异步函数内返回清理函数的问题。
   - [ ] `pop-bar/index.tsx`、`CanvasToolMenu.tsx`、`CanvasViewMenu.tsx` 的 `onChange` 订阅移入 `useEffect` 并在清理时注销。
   - [ ] `Chat.tsx` 事件订阅只绑定一次（ref 保存最新回调）；去重逻辑移入 reducer，`setPending` 移出 `produce`。
   - [ ] 抽取统一场景修改 helper `mutateSceneElements`（自动递增 `version`、`versionNonce`、`updated`），同步修复 `CanvasTextBackground.tsx`。
   - [ ] 画布加载失败显示错误与重试按钮。
4. [ ] 鉴权补强
   - [ ] 登录失败按来源计数，5 次失败锁定 15 分钟；`X-Forwarded-For` 仅在请求来自本机代理时采信。
   - [ ] 启动时访问码少于 16 个字符拒绝启动并提示。
   - [ ] 会话改为 HMAC 签名令牌（secret 由访问码 + `user_data` 随机盐派生），后端重启不掉线，更换访问码后旧会话失效。
   - [ ] 记录 Socket `sid → 会话`；登出时断开对应连接，定时断开过期连接。
   - [ ] 前端封装统一请求函数，收到 401 时切回 AuthGate。
   - [ ] 页面响应增加 `X-Frame-Options: DENY` 与基础 CSP。
5. [ ] 画布快速改进
   - [ ] E2：选中箭头/线条/形状时浮动条提供线宽档位 1、2、4、6、8、12、16、24 与自定义输入，经 `mutateSceneElements` 写入。
   - [ ] E1①：整合为统一补丁脚本 `react/scripts/patch-excalidraw.mjs`，同步修补 `getArrowheadPoints`（箭头头部等比缩放 + 开放箭头半角微调）、`getCanvasPadding`（防 `20px` 离屏裁剪）与 `getDashArrayDashed`/`getDashArrayDotted`（粗虚线缩放）；画布与 SVG 导出一致。
   - [ ] E1②：块箭头工具（直箭头、双向、弯箭头等），闭合 `line` 多边形（`roundness: null`、`roughness: 0`）+ `customData.kind = 'block-arrow'`，可改填充色、描边、头宽、尾宽，缩放时按参数重算顶点。
   - [ ] E3：工具栏增加菱形、Frame、橡皮擦、激光笔、块箭头，按组折叠。
   - [ ] E4：底部栏提供撤销、重做、缩放百分比、适配画布。
   - [ ] E14：能用 `UIOptions` 关闭的原生界面改为配置关闭，其余隐藏规则集中到一个样式块并注明原因。
6. [ ] 验证与收尾：检查 diff；更新 `Docs/` 规划文档状态；不提交、不推送。

### 完成标准

- 后端测试（`server/.venv/Scripts/python.exe -m unittest discover -s tests -v`，注明当前 `server/.venv` 未装 `pytest`，且 `IsolatedAsyncioTestCase` 需本机 loopback socket）新增并通过：`safe_join` 穿越用例、`comfy_dynamic` 路径校验与种子保留、`/api/file` 非法文件名、ComfyUI 代理拒绝外部 URL、`GET /api/config` Key 掩码、路由 404 不被吞成 500、上传超限、缩略图保留、删除级联、登录限流、签名令牌过期与换码失效。
- 前端测试（Windows PowerShell 下用 `npm.cmd run test:run`）新增并通过：`onChange` 订阅清理、`mutateSceneElements` 版本号递增、箭头尺寸缩放与 padding 计算、块箭头顶点生成、401 处理；`react` 下 `npm.cmd run build` 通过。
- 补丁脚本 `patch-excalidraw.mjs` 锚点找不到或版本不匹配时让安装直接报错，并有 Vitest 单测覆盖。
- 手工验证：生成图片期间连续编辑画布 10 次无元素丢失；首页缩略图在工具写入后仍存在；线宽 16 的箭头头部等比放大且四边不被裁剪、虚线不粘连；块箭头可拉伸并导出 PNG/SVG；界面可撤销/重做；错误访问码 5 次后被锁；后端重启后已登录浏览器无需重新登录。
- 未执行项和遗留问题记录在本节末尾。

### 已确认决策

- Agent 引擎采用 earendil-works/pi，新增 Node Agent 服务（M2 实施）。
- Agent 服务目录为仓库根目录 `agent/`，与前端共享 `packages/shared`（事件与工具 schema）。
- 画布继续使用 Excalidraw，按 7.4 与 `Docs/06-Jaaz AIGC无限画布详细技术设计.md` 第 4 节增强。
