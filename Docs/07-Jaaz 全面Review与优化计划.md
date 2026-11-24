# Jaaz 全面 Review 与优化计划

> 日期：2026-11-24
> 范围：M0 加固（安全、数据一致性、已知 bug、鉴权、画布快速改进）与 M1 主体（去云端、`workflows/` 成对工作流与 `workflows/source/` 自动导入、ComfyUI 多实例、三协议模型）。
> 方法：读代码、跑 grep 与脚本实测。未启动 ComfyUI，未实机出图/出视频，相关结论标注"待实机验证"。
> 基线：本地 `main` 提交 `382acc0`；`workflows/source/` 机制与 10 个新工作流包在工作区，未提交。

## 1. 结论摘要

- 功能面：去云端、成对工作流、多实例、三协议、`workflows/source/` 自动检测均已落地，后端 68/68、前端 54/54、构建通过。
- 主要风险集中在 4 处：打包后 `workflows/` 不可用、CI 不跑测试、工作流导入命名冲突会静默覆盖、ComfyUI 多实例的并发/任务状态只做了一半。
- 另有依赖残留、调试路由、LLM 适配器无重试与伪流式、工具描述 token 成本偏高等 P1/P2 项。

## 2. 问题清单

优先级：P0 影响交付或会丢数据；P1 影响稳定性、成本或安全面；P2 可维护性与体验。

### 2.1 P0

| 编号 | 问题 | 证据 | 建议 |
| --- | --- | --- | --- |
| R-01 | 打包后 `workflows/` 不可用 | `package.json` 的 `extraResources` 只含 `server/dist/`、`react/dist/`；`comfy_workflow_pack.py` 用 `__file__` 上三级推 `REPO_ROOT`，PyInstaller 冻结后指向临时解压目录，不可写 | 工作流目录改为可配置：环境变量 `JAAZ_WORKFLOWS_DIR`；Electron 传入 `userData/workflows`；首次启动从随包 `workflows/` 复制默认包；`source/` 同理 |
| R-02 | CI 只构建、不跑测试 | `.github/workflows/build.yml` 里只有构建与发布步骤，没有 `unittest`、`vitest`、`tsc` | 增加 test job：后端 `unittest`、根目录 `npm run test:run`、`cd react && npm run build`；失败时不进入打包 |
| R-03 | 工作流命名冲突会静默覆盖 | 实测草稿命名：6 个中文文件都变成 `MiniMax_H3`，两个图像工作流都变成 `MiniMax_H3_Image`；`save_pack_to_workflows_dir` 写同名目录不检查来源 | 写入前比对已有包的 `source_file`：不同则自动加数字后缀或报错；LLM 返回重名同样处理；加单测 |
| R-04 | 启动即自动调用 LLM 导入，无确认 | `main.py` 检测到新文件且配置了模型就后台导入，消耗 token | 默认只提示；设置里加"自动导入 workflows/source/"开关（默认关）；Ollama 探测不放在启动路径 |

### 2.2 P1

| 编号 | 问题 | 证据 | 建议 |
| --- | --- | --- | --- |
| R-05 | 发给 LLM 的摘要过大 | 文生图摘要约 2.2 万字符，多参考图编辑约 2.1 万字符，来源是 15823 字符的 `task_prompt` 与长分镜脚本 | `summarize_api_json_for_agent` 对长字符串截断（建议 200 字符 + 总长度），保留 `input_type` 与 `options` |
| R-06 | Agent 工具描述重复且偏长 | `_build_input_schema` 已把 `options` 追加到参数描述，工作流 `description` 与参数描述又各写一遍 8 项枚举；12 个工作流每轮对话都全量下发 | 去掉描述文本里的重复枚举；工作流 `description` 控制在 600 字内；评估按 `capability` 分组按需暴露工具 |
| R-07 | `max_concurrency` 只存不用 | grep 仅见读写字段，无信号量或排队 | 按实例建 `asyncio.Semaphore(max_concurrency)`；排队时给前端进度提示 |
| R-08 | 实例选择不看健康与能力 | `resolve_instance` 取第一个启用实例；`capabilities_json` 与健康快照未参与 | 选择顺序：显式 `instance_id` → 启用且在线且支持该 `capability` → 优先级；全部离线时给出明确报错 |
| R-09 | 任务状态重启后残留 | `jobs.status='running'` 在崩溃或重启后无人收尾；`_active_prompts` 在内存中 | 启动时把遗留 `running` 置为 `interrupted`；取消接口按 DB 兜底 |
| R-10 | 上传去重缓存可能指向已被清理的远端文件 | 缓存键只有 `(instance_id, sha256)`，值是远端文件名，没有存在性校验；实例改 URL 后缓存仍命中 | 键加入 `base_url`；命中时用 `/view` 或 `/upload` 重试策略：提交失败且报文件不存在时清缓存重传一次 |
| R-11 | LLM 适配器无重试、伪流式 | `_astream` 先 `_agenerate` 再整体输出一个 chunk；无 429/5xx 退避；Anthropic 每次调用新建 client；`temperature` 对 Anthropic 未传 | 实现真流式（Anthropic `messages.stream`、Gemini `streamGenerateContent`）；加指数退避（最多 3 次）；复用 client；补 `usage_metadata` |
| R-12 | 调试路由暴露 | `ssl_test.py` 注册 `/api/test_ssl`、`/api/test_ssl_full`、`/api/ssl_status`，324 行 | 删除，或仅在 `JAAZ_DEBUG=1` 时注册 |
| R-13 | Python 依赖残留 | `requirements.txt` 中 `mcp`、`openai-agents`、`aiosqlite`、`gunicorn`、`piexif` 在服务端代码中 0 处 import；`requests` 仅 1 处；`anthropic`、`langchain-core` 已被新代码直接依赖但未固定版本 | 逐个确认后移除；固定 `anthropic`、`langchain-core` 版本；`pyinstaller` 移到开发依赖；以 PyInstaller 实际打包 + `pip check` 验证 |
| R-14 | 可选媒体槽位不连续可能报错（待实机验证） | 运行期裁剪未传的 `LoadImage/LoadAudio`，动态输入 `ref_images.ref_image_N` 可能出现缺口 | 实机验证；若不允许缺口，则裁剪时把后续槽位前移，或在 description 要求按顺序填写 |
| R-15 | 工具注册窗口 | `tool_service.py:39` 的 TODO：启动时工具未就绪的竞态 | 启动完成前 `/api/list_tools` 返回 503 或等待就绪事件 |
| R-16 | 目录同步缺并发保护 | 启动后台导入与页面 `auto_sync` 可能同时写同一包目录 | 模块级 `asyncio.Lock` 包住 `sync_workflows_dir_to_db` 与 `auto_import_new_source_workflows` |

### 2.3 P2

| 编号 | 问题 | 建议 |
| --- | --- | --- |
| R-17 | 文件过大：`comfy_workflow_pack.py` 1131 行、`db_service.py` 873 行、`comfyui_router.py` 771 行、`llm_adapters.py` 752 行 | 拆分：`pack/{validate,scan,repair,source,export}.py`；`db_service` 按表拆 repository；`llm_adapters` 按协议拆文件 |
| R-18 | 宽泛 `except Exception:` 14 处，部分吞掉异常 | 全部改为记录日志（带 `exc_info`），只在确有降级意义时吞掉 |
| R-19 | `print` 日志含 emoji，无级别与脱敏统一出口 | 引入 `logging`，统一密钥与路径脱敏过滤器 |
| R-20 | 数值参数类型：默认值为整数时 Pydantic 推成 `int`，Agent 传 7.5 会校验失败 | `_python_type` 对 `number` 统一用 `float`（`seed`/整数类参数用显式 `integer` 类型扩展） |
| R-21 | 前端包体大：`subset-shared` 1.82 MB、`percentages` 1.50 MB、`index` 912 KB，另有大量图表类 chunk | 对 Excalidraw 子集字体、MDX 编辑器、图表相关依赖做动态 `import()`；设置 `manualChunks`；记录首屏体积基线 |
| R-22 | `tsconfig` 中一处 `noUnusedLocals/Parameters` 被注释 | 打开并清理告警 |
| R-23 | 测试：`test_repo_installed_workflow_packs_*` 依赖真实 `workflows/` 内容与子进程；全量用时 5 秒涨到 35 秒 | 改用临时目录夹具；子进程用例合并；目标全量 < 15 秒 |
| R-24 | 缺少 ComfyUI 端到端模拟测试 | 用本地 fake ComfyUI（HTTP + WS）覆盖提交、进度、`/history` 降级、取消、鉴权头、子路径反代 |
| R-25 | `GET /workflows` 每次扫描全部包并对源文件算哈希 | 以目录 mtime + 文件大小做缓存，变化时才重扫 |
| R-26 | 遗留 TODO：`chat_service.py:51` 系统提示词未持久化；`websocket_service.py:22` 广播缺 `canvas_id` | 并入 M2 Agent 改造一起处理 |
| R-27 | `workflows/source/` 含个人提示词与示例图名 | 决定是否进仓库；不进则加入 `.gitignore`，仓库只保留 `workflows/<name>/` 成品包 |
| R-28 | 文档未同步 | 更新 `todo.md`、`Docs/06`（`source/` 机制、10 个工作流参数表）、`Docs/00` 索引 |

## 3. 优化计划

### 阶段 A：交付与数据安全（P0，预估 1 天）

1. R-01 工作流与 `source/` 目录可配置，Electron 传 `userData` 路径，首次启动复制默认包。
2. R-02 CI 加测试 job。
3. R-03 命名冲突保护与单测。
4. R-04 自动导入开关，默认关闭。

完成标准：
- 打包产物（Windows）启动后，设置页能列出随包工作流，且新导入的包写入用户目录。
- CI 在 PR 上跑后端与前端测试，故意让一个用例失败时流水线变红。
- 两个同名但来源不同的工作流导入后得到两个独立目录。
- 默认配置下启动不产生 LLM 请求。

### 阶段 B：稳定性、成本与安全面（P1，预估 2–3 天）

1. R-05、R-06 摘要截断与工具描述瘦身；测量前后 token 数。
2. R-07、R-08、R-09、R-10 ComfyUI 实例并发、选择、任务收尾与上传缓存。
3. R-11 适配器真流式与重试。
4. R-12、R-13 删除调试路由与依赖清理，PyInstaller 实际打包验证。
5. R-15、R-16 工具就绪与并发锁。
6. R-14 实机验证（需启动 ComfyUI）。

完成标准：
- 摘要平均 < 6000 字符；12 个工作流工具描述总长度较现状下降 ≥ 30%。
- 两个并发请求打到 `max_concurrency=1` 的实例时第二个排队而不是并发提交。
- 强杀进程后重启，`jobs` 表无 `running` 残留。
- 流式输出首 token 延迟低于非流式整体延迟；模拟 429 时自动退避重试成功。
- `pip check` 无冲突，打包产物可启动，`/api/test_ssl*` 返回 404。

### 阶段 C：可维护性与体验（P2，预估 2–3 天，可分批）

1. R-17、R-18、R-19 拆文件、异常与日志整理。
2. R-20 数值类型。
3. R-21、R-22 前端体积与类型检查。
4. R-23、R-24、R-25 测试与缓存。
5. R-27、R-28 仓库内容与文档。

完成标准：
- 单文件不超过 600 行（新拆出的文件）；`except Exception:` 无裸吞。
- 首屏主 chunk 较现状下降 ≥ 30%。
- 后端全量测试 < 15 秒，fake ComfyUI 用例覆盖 5 条主路径。
- `todo.md` 与 `Docs/06` 与代码一致。

## 4. 验证清单

- 后端：`Push-Location "server"; .\.venv\Scripts\python.exe -X dev -m unittest discover -s tests -v`
- 前端：根目录 `npm.cmd run test:run`；`cd react; npm.cmd run build`
- 工作流：`server\.venv\Scripts\python.exe server\scripts\workflow_cli.py check-source`、`list`
- 打包：`npm run build:win` 后在干净目录启动，检查工作流列表、写入目录与日志
- 代码质量：`git diff --check`；`.md` 文件为 UTF-8 BOM + CRLF

## 5. 待你决定

1. R-04 自动导入：默认关闭加开关，还是保持"配置了模型就自动导入"？
2. R-06 工具暴露：继续全量下发，还是按 `capability`/用户选择分组按需暴露？
3. R-27 `workflows/source/`：进仓库，还是加入 `.gitignore` 只留成品包？
4. 阶段顺序：先做 A，再做 B；是否把 R-14 实机验证提前（需要你启动 ComfyUI）？

## 6. 执行进度（2026-11-24，按第 5 节决策执行）

决策：自动导入默认关闭手动开启；工具按能力分组；`workflows/source/` 进仓库；先优化后实机测试。

| 编号 | 状态 | 说明 |
| --- | --- | --- |
| R-01 | 已完成 | `JAAZ_WORKFLOWS_DIR`；冻结时用 `USER_DATA_DIR/workflows`；`extraResources` 带 `workflows/`；Electron 传 `JAAZ_BUNDLED_WORKFLOWS_DIR`，启动时 `seed_bundled_workflows` 只复制不存在的包。打包产物待实测 |
| R-02 | 已完成 | `build.yml` 新增 `test` job（后端 unittest、根目录 vitest、前端 build），`build` 依赖它 |
| R-03 | 已完成 | 非 ASCII 名称加短哈希；`unique_pack_name` 自动后缀；`save_pack_to_workflows_dir` 拒绝覆盖其他来源 |
| R-04 | 已完成 | `workflow_settings.json` 开关默认关；`GET/PUT /workflows/source_settings`；设置页加 Switch；启动仅提示 |
| R-05 | 已完成 | 摘要字符串截断到 200 字符 |
| R-06 | 已完成 | 工具按 `capability` 分为 `image_creator` / `video_creator` / `audio_creator`，规划智能体与各组互相交接；参数枚举描述去重，10 个包说明总长约 9000 字符 |
| R-07 | 已完成 | `acquire_slot` 按实例 `max_concurrency` 排队 |
| R-08 | 已完成 | `resolve_instance(capability)`：启用 → 支持能力 → 已知离线靠后；无匹配时退回全部启用实例 |
| R-09 | 已完成 | 启动时对无 `remote_prompt_id` 的任务执行 `interrupt_stale_jobs`；已知 `remote_prompt_id` 的运行中任务由 `job_recovery.py` 后台轮询 `/history` 取回产出写回原画布 |
| R-10 | 部分完成 | 缓存键含 `base_url`；"远端文件已被清理时自动重传"未做 |
| R-11 | 部分完成 | OpenAI 兼容通道 `max_retries=5` 并增加 429 友好提示；Anthropic SDK `max_retries=3`；Gemini 5xx/429/网络错误指数退避；Anthropic/Gemini 均为真流式并带回退。未做：HTTP client 复用、`usage_metadata` |
| R-12 | 已完成 | `ssl_test` 仅在 `JAAZ_DEBUG=1` 注册 |
| R-13 | 已完成 | 移除 `mcp`、`openai-agents`、`aiosqlite`、`gunicorn`、`piexif`；`anthropic>=2.11,<3`、`langchain-core>=0.3.86,<0.4`；`pip check` 通过 |
| R-14 | 已验证 | 多槽位工作流说明已加"按顺序填写"，并在 Colab ComfyUI 0.46.0 实机验证单图裁剪可选 `LoadImage` 槽位出图通过 |
| R-15 | 已完成 | `tool_service.ready` 与 `/list_tools` 等待首轮注册 |
| R-16 | 已完成 | 同步与自动导入各加进程内锁 |
| R-20 | 已完成 | `number` 参数统一 `float`，写回时整数默认值还原为整数 |
| R-22 | 未做 | 试开 `noUnusedLocals/Parameters` 报 53 处既有错误，已回退，留待阶段 C 清理 |
| R-17/18/19/21/23/24/25/26/27/28 | 未做/部分 | R-27 已按决定进仓库；R-28 已补本节与 `Docs/06` 附录；其余留待阶段 C |

新增测试：`server/tests/test_optimization_r01_r16.py`（15 个用例）。

## 7. 实机端到端验证记录（Colab ComfyUI 0.46.0 / NVIDIA L4）

1. **文生图（`text2image_minimax_h3`）**：新建画布 `e2e-cfd4e175d2`，`planner -> image_creator` 路由通过，`remote_prompt_id` 落库，约 60 秒生成 `fU6DEtHfDI.png` 并写入画布元素与会话消息。
2. **多参考图编辑 + 可选槽位裁剪（`image_edit_multiref_minimax_h3`）**：新建画布 `e2e-9601e99aa4`，仅传 1 张底图并自动裁剪节点 `35`/`36`，约 64 秒生成 1024×1024 图片 `QKUppYoBzl.png` 并写入画布与消息。
3. **首帧图生视频 + 无总超时验证（`image2video_first_frame_minimax_h3`）**：新建画布 `e2e-29d4c891f2`，`planner -> video_creator` 路由通过，耗时 1001 秒（约 16 分 41 秒，跨越原 600 秒限制无超时中断），生成含 AAC 音轨的 640×640 MP4（`IQK1t10hpk.mp4`）并写入画布 `video` 元素与会话消息。
4. **全量 12 个工作流对 Colab `/object_info`（1952 个节点类）核验**：
   - `text2image_MOSS`、`ImageEdit_MOSS`、`text2image_minimax_h3`、`image_edit_multiref_minimax_h3`、`text2video_minimax_h3`、`image2video_first_frame_minimax_h3`、`image2video_first_last_frame_minimax_h3`、`ref2video_minimax_h3_ref2va`、`ref2video_multiref_minimax_h3_rh`、`video_upscale_seedvr2_3b` 共 10 个工作流节点与模型权重全部就绪。
   - `ref2video_dual_minimax_h3_fl2va_turbo`（ID 15）：已将旧版权重名修正映射为线上 L4 实际文件（`minimax_h3_fl2va_pruned_int8_convrot.safetensors`、`minimax_h3_video_vae_int8_convrot.safetensors`、`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`），并移除依赖未安装 `sageattention` 包的 `PathchSageAttentionKJ`（节点 98）与 `MiniMaxH3MemoryEfficientSageAttentionPatch`（节点 99），直连 `105 -> 84/87` 后实机双参考出片通过。
   - `ref2video_multimodal_minimax_h3_rf`（ID 16）：已移除无下游消费者的预览节点 `ShowAnything|Mie`（节点 24/25）及 `PathchSageAttentionKJ`（节点 20，直连 `4 -> 22`），全量 12 个工作流静态与节点依赖校验 100% 就绪。
5. **同一画布多场景深度综合实测（`e2e-story-a350f150` / 会话 `e2e-sess-e7299ecb`）**：
   - **空白画布建稿与多图形故事板铺设**：通过新增空白画布入口创建画布，铺设 2 个画框（`frame`）、2 张矩形脚本卡（`rectangle` + 绑定 `text`）、1 个独立分镜文字框、1 个菱形（`diamond` + 绑定文字）、1 个椭圆（`ellipse`）、2 条普通箭头（含负宽高箭头）以及直/弯 2 个自定义块箭头（`blockArrow`）。
   - **文字框直接作为脚本生图（Turn 1 & Turn 2）**：对话未粘贴脚本正文，智能体直接从 `<canvas_scene_context>` 读取【脚本卡1·主角设定】与【脚本卡2·道具特写】，依次生成宋制汉服女子主视觉 `zhKReP6U7-.png`（坐标 `755, 60`）与天青釉冰裂纹茶盏 `yKEZDjMjEy.png`（坐标 `1819, 60`），自动避让左侧故事板与用户审片批注文字框。
   - **跨轮多图融合与持续精修（Turn 3 & Turn 4）**：在同一会话内直接引用画布图像 `#1` 与 `#2` 的 `file_id`，调用 `image_edit_multiref_minimax_h3` 将冰裂纹茶盏融合至女子手中产出 `Sv_OEbq2k2.png`（坐标 `2883, 60`）；随后基于图像 `#3` 持续修改为傍晚微雨与室内暖黄灯笼光影产出 `PKVpr-ZmWF.png`（坐标 `3947, 60`），人物面容、服饰、竹叶与茶盏高度一致。
   - **同会话跨能力交接 + 双参考图生视频自动换行排版（Turn 5）**：在连续 4 轮图像生成后，同一会话自动完成 `image_creator -> video_creator` 交接，读取【脚本卡3·动态分镜】并传入图像 `#4` 与 `#2`，通过修复后的 `ref2video_dual_minimax_h3_fl2va_turbo`（ID 15）耗时 920.5 秒产出 5.17 秒带 AAC 音轨的 640×640 视频 `fa3_mfiYnr.mp4`，自动换行落位至第 2 行（坐标 `755, 1124`），全画布 21 个元素零面积重叠。
