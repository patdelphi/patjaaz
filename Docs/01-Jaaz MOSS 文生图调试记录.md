# Jaaz MOSS 文生图调试记录

更新日期：2026-11-22

## 工作流信息

- Jaaz 工作流名称：`text2image_MOSS`
- 类型：ComfyUI 文本生成图片
- ComfyUI 地址：`https://colab.patdelphi.xyz`
- 工作流配置存储：Jaaz 本地数据库 `server/user_data/localmanus.db`
- 主要输入：
  - `positive_prompt`：正向提示词
  - `aspect_ratio_19`：画面比例，必须使用 ComfyUI 下拉列表中的完整选项
  - `megapixels_19`：输出像素规模

## 故障与原因

### 1. 工作流必填参数未匹配

ComfyUI 节点输入别名曾显示为 `value_18:17`，而 Jaaz 调用传入的是 `positive_prompt`。输入名称不一致会导致必填参数无法正确传递。

**处理：** 将该输入别名改为 `positive_prompt`，并补充输入描述；同时核对比例和像素参数的别名及描述。

### 2. 比例值不符合节点枚举

ComfyUI 日志显示 `ResolutionSelector 19` 拒绝了 `2:3` 和 `1:1`。节点只接受下列完整枚举值：

- `1:1 (Square)`
- `2:3 (Portrait Photo)`
- `3:2 (Photo)`
- `3:4 (Portrait Standard)`
- `4:3 (Standard)`
- `9:16 (Portrait Widescreen)`
- `16:9 (Widescreen)`
- `21:9 (Ultrawide)`

**处理：** 更新工作流及 `aspect_ratio_19` 的说明，要求调用时原样传入完整枚举值，不要缩写。

### 3. ComfyUI 无输出时 Jaaz 曾报告成功

此前 WebSocket 事件没有返回输出时，Jaaz 没有从 ComfyUI 历史记录补取图片，也可能把无图片结果当作成功。

**处理：** 后端在 WebSocket 未收到输出时读取 ComfyUI `/history`；若最终没有图片或视频输出，则返回明确错误，避免显示假成功。

## 修改记录

- 工作流参数别名和描述已校正。
- 比例参数说明已补充完整枚举。
- Jaaz 图片输出处理已增加 `/history` 回查和空输出错误提示。
- 保存了比例配置修改前的数据库备份：
  `server/user_data/text2image_MOSS-before-aspect-ratio-fix-20261122T142420Z.sqlite`

## 验证结果

- `server/tests/test_comfyui_history.py`：4 项单元测试通过。
- Python 语法检查通过，相关 diff 检查通过。
- Jaaz 后端重启后，本地 API 返回 HTTP 200，MOSS 工具已注册，Dashscope 的 `qwen3.7-plus` 可用。
- 使用 `aspect_ratio_19="1:1 (Square)"`、`megapixels_19=1` 完成一次端到端生成。
- Jaaz 工具返回成功；测试画布 `LVobxaHjuim3mFVlL7mUL` 中记录到 1 个图片元素。
- 本次 ComfyUI 生成耗时约 2 分 57 秒；Jaaz 请求总耗时约 3 分 31 秒。

生成文件：

| 位置 | 文件 | 大小 |
| --- | --- | ---: |
| ComfyUI 输出目录 | `H:\我的云端硬盘\comfyui\output\moss\moss_image_t2i_00096_.png` | 988,327 字节 |
| Jaaz 本地缓存 | `server/user_data/files/zHi1jbuVSe.png` | 899,457 字节 |

## 补充说明

- 用户提供的 ComfyUI 日志中，前两次任务因比例枚举值不匹配被拒绝；修正后生成成功。
- 本地环境直接访问远程 `/history` 曾被 Cloudflare 拒绝；端到端验证通过 Jaaz 后端连接完成，并以 ComfyUI 输出文件及画布图片元素作为结果证据。
- 曾有一次调试请求因测试脚本把 `text_model` 传成数组而返回 HTTP 500；该请求在模型和 ComfyUI 调用前失败，修正请求结构后的端到端测试通过。
- 本记录对应的代码改动尚未 commit 或 push。

## 相关代码

- `server/routers/comfyui_execution.py`
- `server/tools/comfy_dynamic.py`
- `server/utils/comfyui_history.py`
- `server/tests/test_comfyui_history.py`

## 2026-11-23 完整 Jaaz -> ComfyUI 测试

### 调用

- 文本模型：DashScope `qwen3.7-plus`。
- 工作流：`text2image_MOSS`，单张 1:1 方形橘猫水彩插画。
- Jaaz 会话 ID：`codex-comfyui-e2e-session-d44e8c9fd43a4d32baccb11532c8da75`。
- 独立测试画布 ID：`codex-comfyui-e2e-f3f32614875c4cc99bb361c1760726e9`。

### 结果

- Jaaz `/api/chat` 返回 accepted；任务状态经过 `TextGenerate 1%`、`K采样器 4%-100%`、`Finalizing generated media...`，最终 `Task completed`，无错误。
- 会话保存 8 条消息，包含 `write_plan`、转交图像代理、`text2image_MOSS` 调用和 3 条工具结果。
- 测试画布保存 1 个图片元素和 1 个关联文件。
- ComfyUI 文件：`H:\我的云端硬盘\comfyui\output\moss\moss_image_t2i_00106_.png`，6,672,234 字节，2048×2048，有效 PNG。
- Jaaz 文件：`server/user_data/files/EA3rE9KfTE.png`，6,546,749 字节，2048×2048，有效 PNG；`/api/file/EA3rE9KfTE.png` 返回 HTTP 200。

本次测试画布保留供检查；没有修改已有用户画布，也没有使用浏览器自动化。
