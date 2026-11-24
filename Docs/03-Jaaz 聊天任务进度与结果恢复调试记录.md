# Jaaz 聊天任务进度与结果恢复调试记录

更新日期：2026-11-23

## 现象

ComfyUI 已经生成图片，Jaaz 聊天仍显示 `Thinking...`，没有持续进度，也没有显示最终回复或把结果图补到画布。

## 根因

1. 聊天进度事件依赖 Socket.IO。客户端断开时，ComfyUI 任务仍可能在后台完成；旧逻辑在结束后删除任务状态，前端轮询失去终态信息，pending 状态没有清除。
2. 图片已经写入画布数据，但画布运行时只在收到 `Canvas::Session::ImageGenerated` 事件时新增图片。事件在断线期间丢失后，当前画布场景没有从已保存数据恢复图片。
3. 同一 `session_id` 重试时，后端无条件插入聊天会话记录，可能触发 `UNIQUE constraint failed: chat_sessions.id`，导致聊天请求返回 500。

## 修复

- 后端按 `session_id` 保留任务运行/完成/失败状态快照，并限制终态缓存数量；同一会话并发提交会被拦截。
- 创建会话记录改为幂等操作，避免重复提交触发主键冲突。
- 前端识别任务终态或已观察到的任务状态消失，读取已保存的会话消息、清除 Thinking 状态，并请求画布从数据库补同步缺失图片。
- 恢复画布图片时跳过没有 `fileId` 的元素，避免空索引。

## 验证

- 后端专项 unittest：3 项通过。
- 前端定向 Vitest：6 项通过。
- 修改过的 Python 文件通过 `py_compile`。
- React `npm run build` 通过，TypeScript 检查和 Vite 生产构建均通过；本次构建转换 4659 个模块。
- 构建前后 `react/src/route-tree.gen.ts` SHA256 一致，已有差异得到保留。

## 当前状态

2026-11-23 已重启 Jaaz 前后端。前端 `http://127.0.0.1:5174` 和后端 `http://127.0.0.1:57988` 均返回 HTTP 200。状态探测接口 `/api/chat/status/restart-probe` 返回 `{"known":false,"active":false}`，确认本次后端代码已加载，探测时没有运行中的聊天任务。

本次没有新提交 ComfyUI 生成任务。在线进度、任务终态回填和画布图片恢复尚未做真实任务复验。

## write_plan 计划卡片 steps 类型错误

更新时间：2026-11-23

### 现象

页面显示 `TypeError: i.steps.map is not a function`，堆栈指向 `percentages-*.js`。

### 原因

`WritePlanToolCall` 将模型返回的工具参数 JSON 直接当成固定 TypeScript 类型使用。`steps` 实际不是数组时，组件仍访问 `.length` 和 `.map()`，触发错误边界并显示整页 Error。

### 修复

- 新增 `parseWritePlanSteps`：只接受对象中的数组 `steps`，过滤非对象、缺少字符串标题的条目；非法 JSON 或非数组返回空列表。
- `WritePlanToolCall` 使用规范化后的步骤数组渲染，不再直接访问未经验证的模型数据。

### 验证

- 参数解析回归测试 3 项通过；与聊天任务状态、聊天 API 定向测试合计 9 项通过。
- TypeScript 检查和 Vite 生产构建通过，转换 4660 个模块。
- 本地 FastAPI 静态资源 `/assets/percentages-BXMCSKIN-C6oBHsd0.js` 返回 HTTP 200，已提供新 bundle；其中包含数组校验，不含原有未经保护的 `parsedArgs.steps.map` 调用。
- `react/src/route-tree.gen.ts` SHA256 保持不变。

无需重启后端；后端静态站点直接读取 `react/dist`。浏览器仍显示错误页时，刷新页面以加载新的 HTML 和 bundle。本次未使用浏览器自动化，也未调用 ComfyUI。

## 实际聊天烟测

2026-11-23 使用已配置的 DashScope `qwen3.7-plus`，经本地 Jaaz `/api/chat` 发送一次只制定计划的短请求。API 返回 accepted，任务状态最终为 `completed`；历史读取到 user、assistant、tool、assistant 共 4 条消息，其中触发 1 次 `write_plan`，`steps` 为包含 2 项的数组，状态快照没有错误。

烟测会话 ID：`codex-writeplan-smoke-20261123151210-cd0e1b0a`。请求没有图像工具，没有调用 ComfyUI，也没有修改画布。

另用 React 服务端渲染直接检查畸形 `steps` 输入：字符串和对象均能正常显示计划卡片，不再触发 `.map is not a function`。此次未使用浏览器自动化；浏览器页面需要刷新后加载新版本。

## MOSS ComfyUI 完整端到端测试

2026-11-23 通过 Jaaz 聊天 API，以 DashScope `qwen3.7-plus` 调用唯一启用的图像工具 `text2image_MOSS`，生成一张 1:1 橘猫水彩插画。请求落在独立画布，未触碰原有画布。

- 任务进度：`TextGenerate 1%`；`K采样器 4%`、`20%`、`44%`、`64%`、`84%`、`100%`；随后 `Finalizing generated media...`、`Task completed`。
- Jaaz 会话：`codex-comfyui-e2e-session-d44e8c9fd43a4d32baccb11532c8da75`；任务终态 `completed`，无错误。
- 测试画布：`Codex ComfyUI E2E 20261123`，ID `codex-comfyui-e2e-f3f32614875c4cc99bb361c1760726e9`；画布数据包含 1 个图片元素和 1 个图片文件。
- ComfyUI 输出：`H:\我的云端硬盘\comfyui\output\moss\moss_image_t2i_00106_.png`，PNG 有效，2048×2048，6,672,234 字节。
- Jaaz 缓存：`server/user_data/files/EA3rE9KfTE.png`；画布引用的 `/api/file/EA3rE9KfTE.png` 返回 HTTP 200、`image/png`，PNG 有效，2048×2048，6,546,749 字节。

本轮确认了进度接收、ComfyUI 完成、聊天终态和画布图片回填。未使用浏览器自动化；测试画布保留供检查。
