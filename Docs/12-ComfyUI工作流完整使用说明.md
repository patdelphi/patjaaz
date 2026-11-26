# Jaaz ComfyUI 工作流完整使用说明

> 更新日期：2026-11-26
> 适用范围：项目 `workflows/` 目录下全部 17 套标准化成对工作流包（含 SenseNova U1.6、MiniMax H3 全系、MOSS-Image 全系与 SeedVR2 超分）

---

## 1. 快速选型总表

用户在画布对话中提出需求时，Agent 只会从 **`enabled = true`（已启用）** 的工作流中选择工具；其余停用工作流可在「设置 -> ComfyUI」随时按开关启用。

| 分类 | 工作流标识 (`name`) | 显示名称 | 当前状态 | 首选适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| 文生图 | `text2image_sensenova_u16` | SenseNova U1.6 文生图 | **已启用** | 中英双语海报、信息图、卡片排版、高美感商业摄影与人像（支持文字自检循环） |
| 文生图 | `text2image_minimax_h3` | MiniMax H3 文生图 | **已启用** | 电影感纪实人像、自然风光、微距静物、复杂空间构图生成 |
| 文生图 | `text2image_MOSS` | MOSS-Image 文生图 | 已停用 | 轻量 5B 模型双语文字排版与二次元/插画生成（已纳入 `workflows/`） |
| 图像编辑 | `image_edit_sensenova_u16` | SenseNova U1.6 图像编辑 | **已启用** | **单底图编辑首选**：增删改局部物体、改服装光影、精准替换画面内中英文文案（自动保持原图比例） |
| 图像编辑 | `image_edit_multiref_minimax_h3` | MiniMax H3 多参考图编辑 | **已启用** | **多图融合与遮罩引导编辑首选**：以底图 `<Picture 1>` 为主，融合 `<Picture 2>`/`<Picture 3>` 或红色高亮引导区 |
| 图像编辑 | `ImageEdit_MOSS` | MOSS-Image 图像编辑 | 已停用 | 1.0 MP 轻量单图局部换色、换材质编辑（已纳入 `workflows/`） |
| 图像编辑 | `image_multiref_moss` | MOSS-Image 多图参考生图 | 已停用 | 1–4 张参考图经 Qwen3.5 视觉提取驱动 MOSS-Image 轻量风格迁移与主体复现 |
| 文生视频 | `text2video_minimax_h3` | MiniMax H3 文生视频 | **已启用** | 无参考图，纯文字分镜脚本直接生成 24fps 视频 + 原生同步立体声音轨 |
| 图生视频 | `image2video_first_frame_minimax_h3` | MiniMax H3 单图首帧生视频 | **已启用** | 指定起始第 1 帧图片，延续生成后续动作、运镜与立体声效 |
| 图生视频 | `image2video_first_last_frame_minimax_h3` | MiniMax H3 双图首尾帧生视频 | 已停用 | 同时指定开场首帧与结束尾帧，生成两帧之间的平滑过渡视频 |
| 参考生视频 | `ref2video_dual_minimax_h3_fl2va_turbo` | MiniMax H3 FL2VA 双图参考生视频 (Turbo) | **已启用** | 用 2 张参考图（如人物 + 道具/坐骑/场景）快速合成全新分镜动作视频（8 步 Turbo） |
| 参考生视频 | `ref2video_dual_minimax_h3_r2v` | MiniMax H3 R2V 双图参考生视频 (8步Turbo) | 已停用 | 基于原生 `MiniMaxH3ReferenceToVideo` + 8 步 Turbo LoRA 的 1–2 图快速参考生视频 |
| 参考生视频 | `ref2video_minimax_h3_ref2va` | MiniMax H3 Ref2VA 参考生视频 | 已停用 | 1–4 张参考图（人物 A/B + 场景 + 道具）20 步高保真角色一致性视频 |
| 参考生视频 | `ref2video_quad_minimax_h3_ref2va` | MiniMax H3 Ref2VA 四元素参考生视频 | 已停用 | 专用四槽位（人物 A + 人物 B + 场景 + 道具）双人对手戏 20 步高保真生视频 |
| 参考生视频 | `ref2video_multimodal_minimax_h3_rf` | MiniMax H3 多图音频参考生视频 (RF加速) | 已停用 | 1–5 张参考图 + 0–3 段参考音频（人声/台词/音乐节奏）联合引导生视频 |
| 参考生视频 | `ref2video_multiref_minimax_h3_rh` | MiniMax H3 开源版双图参考生视频 (RH) | 已停用 | 依赖 `ComfyUI-RH-MiniMax-H3` 插件与独立模型目录，当前实例未装对应目录 |
| 视频超分 | `video_upscale_seedvr2_3b` | SeedVR2 3B 视频超分 | 已停用 | 单段超分底座（长视频请优先使用内置分块断点超分工具 `video_upscale_chunked`） |

---

## 2. 通用参数与提示词规范

### 2.1 画幅比例（`aspect_ratio`）与像素档（`megapixels`）

除 `ref2video_multiref_minimax_h3_rh` 使用短比例（如 `"9:16"`）外，其余所有带比例选择的工作流均使用 ComfyUI `ResolutionSelector` 完整枚举值，调用时必须原样传入完整字符串：

| 枚举值（必须完整传入） | 4.0 MP 图像尺寸（H3 / SenseNova） | 0.98 MP 视频原生 768p 尺寸（H3 视频） |
| :--- | :--- | :--- |
| `"1:1 (Square)"` | `2048 × 2048` | `992 × 992` |
| `"3:4 (Portrait Standard)"` | `1760 × 2368` | `864 × 1152` |
| `"4:3 (Standard)"` | `2368 × 1760` | `1152 × 864` |
| `"2:3 (Portrait Photo)"` | `1632 × 2464` | `800 × 1216` |
| `"3:2 (Photo)"` | `2464 × 1632` | `1216 × 800` |
| `"9:16 (Portrait Widescreen)"` | `1536 × 2720` | `768 × 1344` |
| `"16:9 (Widescreen)"` | `2720 × 1536` | `1344 × 768` |
| `"21:9 (Ultrawide)"` | `3136 × 1344` | `1536 × 640` |

- **像素档不可随意压低**：MiniMax H3 Image 与 SenseNova U1.6 的有效训练区间均为 `4.0 MP` 起（低于 `2.0 MP` 会出现涂抹与五官细节劣化）；MiniMax H3 视频原生画幅为 `0.98 MP`（768p），MOSS-Image 推荐区间为 `1.0–2.0 MP`。

### 2.2 多图与多音频引用标签语法

- 在 `image_edit_multiref_minimax_h3`、`image2video_*` 与 `ref2video_*` 系列中，传入的多路素材在视觉编码器内按连接顺序映射为 **`<Picture 1>`**、**`<Picture 2>`**、**`<Picture 3>`**……，参考音频映射为 **`<Audio 1>`**、**`<Audio 2>`**……。
- 提示词中必须直接写 `<Picture 1>`、`<Picture 2>` 指代对应素材，严禁写 ComfyUI 内部端口名（如 `ref_images.ref_image_0`）。
- 可选参考图或参考音频必须**按编号顺序连续填写**（如两张图填 `reference_image_1` 和 `reference_image_2`，不要跳过 `2` 直接填 `3`）；未填的可选媒体节点由 Jaaz 后端在提交前自动裁剪。

### 2.3 画面内文字与双端文件存储

- **文字渲染**：需要在海报、招牌、字幕卡中原样显示的文字，在提示词中统一用双引号 `"..."` 括起。
- **双端存储路径**：
  - ComfyUI 远端按工作流 `SaveImage` / `SaveVideo` 节点的 `filename_prefix` 落盘：SenseNova 图像存入 `output/sensenova/`，MiniMax H3 图像存入 `output/minimax_h3_image/`，所有视频工作流统一存入 `output/video/`。
  - Jaaz 本地后端会自动将成片下载至 `server/user_data/files/` 扁平目录并重命名为短 ID 文件，远端实例关闭后本地画布仍可离线浏览与导出。

---

## 3. 三大类核心开关使用指南

### 3.1 加速采样开关（`turbo_mode` / `enable_lightning_lora`）

不同模型的加速 LoRA 成熟度差异很大，不能一刀切全开或全关：

1. **SenseNova U1.6（`turbo_mode`）**：
   - `true`（默认）：启用 8 步 LoRA，采样自动联动切为 **`steps = 8, CFG = 1.0`**，单图热态约 45–90 秒，适合人像、摄影、插画、普通海报大标题及日常局部改图。
   - `false`：关闭 LoRA 走 Quality 模式，采样联动切为 **`steps = 50, CFG = 4.0`**，耗时增加约 4–5 倍，适合包含多栏小字、复杂图表、密集配料表等对笔画精度要求极高的版面。
2. **MiniMax H3 FL2VA 视频系列（`text2video` / `first_frame` / `first_last_frame` 的 `enable_lightning_lora`）**：
   - `true`（默认）：启用官方成熟的 **8 步 `v1.0` Turbo LoRA**（联动切为 `8` 步），5 秒 768p 视频热态约 8 分钟，运动连贯度与立体声音质稳定，日常强烈建议保持 `true`。
   - `false`：切回基础模型 `20` 步采样，单条耗时约 18–22 分钟，仅在追求极限光影细节时手动关闭。
3. **MiniMax H3 Ref2VA 专用参考视频（`ref2video_minimax_h3_ref2va` 的 `enable_lightning_lora`）**：
   - `false`（默认）：走 `20` 步完整采样 + `normal` 调度器。原因是 Ref2VA 目前仅有早期的 **4 步 `v0.1` LoRA**，官方模板已明确提示开启后会明显损失画质与角色还原度，仅在快速预览构图草稿时才临时设为 `true`。

### 3.2 提示词增强开关（`enable_prompt_enhancer` / PE）

| 工作流 | 默认值 | 内置扩写模型 | 开关判断规则 |
| :--- | :--- | :--- | :--- |
| `text2image_sensenova_u16` | `true` | `qwen3.5_9b_qwen_image_2.1_pe_t2i` | 日常保持 `true`，自动补齐构图、光影与版式层级；仅在需要逐字锁死超长排版原文时传 `false`。 |
| `image_edit_sensenova_u16` | `true` | `qwen3.5_9b_qwen_image_2.1_pe_i2i` | **推荐保持 `true`**：该节点会**同时读取底图像素与文字指令**，自动定位被改物体并补全背景保护描述。 |
| `text2image_minimax_h3` | `true` | `qwen3.5_9b_w4a8_gptq` | 日常保持 `true`，将简短或中文描述转为 H3 原生训练分布的英文高密度视觉描述并保留引号内文字；锁死大段中文排版不许改字时传 `false`。 |
| `image_edit_multiref_minimax_h3` | 内部锁死 `false` | 不启用（已隐藏参数） | 子图内原扩写器无图像输入且按纯文生图改写，开启会抹掉 `<Picture 1>`~`<Picture 3>` 标签，故已在工作流内固定关闭且不向 Agent 暴露。 |
| `text2image_MOSS` | `true` | 复用主编码器 `qwen3.5_9b` | 零额外显存开销，保持 `true`。 |

### 3.3 SenseNova 自主自检修正开关（`self_correction`）

SenseNova U1.6 独有「生成 → 视觉自检核对文字/编号 → 重绘修正」闭环（最多循环 5 轮）：
- **`false`（默认，基础单次链路）**：人像、风景、静物摄影、插画，以及普通光影/颜色/材质/增删物件的图像编辑，一律保持 `false`；每一轮自检都会多跑一次完整采样，非密集文字场景开启只会成倍增加耗时。
- **`true`（自检修正链路）**：生成或编辑**多区块商业海报、步骤流程图、数据图表、带多行中英文标签的信息图**时设为 `true`，模型会自动检查错别字、漏字与乱码并重绘修正（搭配 `turbo_mode = false` 文字准确率最高）。

---

## 4. 全部 14 套工作流逐项参数详解

### 4.1 文生图工作流（3 套）

#### （1）`text2image_sensenova_u16` — SenseNova U1.6 文生图【已启用】
- **目录**：`workflows/text2image_sensenova_u16/`
- **内置模型**：`sensenova_u1.6_8b_mot_int8_convrot.safetensors` + `sensenova_u1.6_8b_mot_8step_lora_bf16.safetensors` + `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors`
- **固定设置**：`euler`、`simple`、`denoise = 1.0`，随机种子自动注入 `Int (Seed)` 节点 `7`；ComfyUI 输出前缀 `sensenova/image_sensenova_u16_t2i`。
- **参数配置**：
  - `positive_prompt`（必填，`string`）：画面描述；需渲染在图上的文字用双引号括起（如 `主标题 "AUTUMN LATTE"`）。
  - `aspect_ratio`（可选，`enum`，默认 `"3:4 (Portrait Standard)"`）：完整比例枚举字符串。
  - `megapixels`（可选，`number`，默认 `4.0`）：保持 `4.0` 原生训练像素档。
  - `turbo_mode`（可选，`boolean`，默认 `true`）：`true` = 8 步 CFG 1.0；`false` = 50 步 CFG 4.0。
  - `self_correction`（可选，`boolean`，默认 `false`）：密集文字排版/信息图传 `true`，普通画面保持 `false`。
  - `enable_prompt_enhancer`（可选，`boolean`，默认 `true`）：启用内置 T2I 扩写。

#### （2）`text2image_minimax_h3` — MiniMax H3 文生图【已启用】
- **目录**：`workflows/text2image_minimax_h3/`
- **内置模型**：`minimax_h3_image_pruned_int8_convrot.safetensors` + `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` + `minimax_h3_image_vae_fp16.safetensors` + `qwen3.5_9b_w4a8_gptq.safetensors`
- **固定设置**：CFG 蒸馏模型，固定 `steps = 8`、`cfg = 1.0`（严禁调高 CFG，否则高光死白过曝）、`euler`、`simple`、`denoise = 1.0`；ComfyUI 输出前缀 `minimax_h3_image/h3_t2i_`。
- **参数配置**：
  - `positive_prompt`（必填，`string`）：画面主体、光影、镜头景别与材质描述。
  - `aspect_ratio`（可选，`enum`，默认 `"3:4 (Portrait Standard)"`）：完整比例枚举字符串。
  - `megapixels`（可选，`number`，默认 `4.0`）：官方有效区间 `4.0–20.0 MP`，保持 `4.0` 兼顾画质与 24GB 显存速度。
  - `enable_prompt_enhancer`（可选，`boolean`，默认 `true`）：启用内置英文视觉扩写器。

#### （3）`text2image_MOSS` — MOSS-Image 文生图【已停用 / 数据库记录】
- **来源**：SQLite `comfy_workflows`（ID `5`）
- **内置模型**：`moss_image_sft_int8_convrot.safetensors` + `qwen3.5_9b_w4a8_gptq.safetensors` + `flux2-vae_small.safetensors`
- **固定设置**：`steps = 25`、`cfg = 2.5`、`er_sde`、`simple`、内置负面提示词；输出前缀 `moss/moss_image_t2i`。
- **参数配置**：
  - `positive_prompt`（必填，`string`）：画面内容描述。
  - `aspect_ratio_19`（可选，`enum`，默认 `"16:9 (Widescreen)"`）：完整比例枚举字符串。
  - `megapixels_19`（可选，`number`，默认 `2.0`）：OpenMOSS 官方推荐 `1.0 / 1.5 / 2.0`（勿超 `4.0` 外推上限）。
  - `enable_prompt_enhancer`（可选，`boolean`，默认 `true`）：启用内置扩写。

---

### 4.2 图像编辑工作流（3 套）

#### （4）`image_edit_sensenova_u16` — SenseNova U1.6 图像编辑【已启用】
- **目录**：`workflows/image_edit_sensenova_u16/`
- **核心特点**：单张底图编辑首选；自动读取底图尺寸并保持原图宽高比输出，无需手动传比例；支持精准修改图中局部文字。
- **内置模型**：`sensenova_u1.6_8b_mot_int8_convrot.safetensors` + `8step_lora` + `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors`
- **参数配置**：
  - `source_image`（必填，`image`）：画布或上传的底图文件名。
  - `edit_instruction`（必填，`string`）：写明修改内容及需保留的部分（例如：`在咖啡杯右侧添置一碟抹茶蛋糕，将副标题从 "秋日限定" 改为 "下午茶甄选"，保持主标题、咖啡拉花与背景光影不变`）。
  - `megapixels`（可选，`number`，默认 `4.0`）：底图缩放与输出总像素档。
  - `turbo_mode`（可选，`boolean`，默认 `true`）：`true` = 8 步 CFG 1.0；精细改小字可设 `false`（50 步 CFG 4.0）。
  - `self_correction`（可选，`boolean`，默认 `false`）：改海报/图表文字时设 `true`，普通改图保持 `false`。
  - `enable_prompt_enhancer`（可选，`boolean`，默认 `true`）：多模态视觉扩写，建议保持开启。

#### （5）`image_edit_multiref_minimax_h3` — MiniMax H3 多参考图编辑【已启用】
- **目录**：`workflows/image_edit_multiref_minimax_h3/`
- **核心特点**：支持 1 张底图 + 最多 2 张附加参考图进行跨图人物/道具/画风融合。
- **固定设置**：`steps = 8`、`cfg = 1.0`、`euler`、`simple`，内置纯文本 PE 固定关闭。
- **参数配置**：
  - `reference_image_1`（必填，`image`）：主底图文件名，对应 `<Picture 1>`。
  - `edit_instruction`（必填，`string`）：编辑指令，须用 `<Picture 1>`、`<Picture 2>`、`<Picture 3>` 指代各图角色（例：`以 <Picture 1> 为底图，保持人物五官与石桥构图不变，让人物右手提着 <Picture 2> 中的莲花灯，天色改为蓝调夜景`）。
  - `reference_image_2` / `reference_image_3`（可选，`image`）：第 2、3 张参考图文件名，留空时自动裁剪节点。
  - `aspect_ratio`（可选，`enum`，默认 `"16:9 (Widescreen)"`）：建议传入与主底图一致的比例枚举值。
  - `megapixels`（可选，`number`，默认 `4.0`）：保持 `4.0`。

#### （6）`ImageEdit_MOSS` — MOSS-Image 图像编辑【已停用 / 数据库记录】
- **来源**：SQLite `comfy_workflows`（ID `6`）
- **固定设置**：`1.0 MP` 等比缩放、`steps = 30`、`cfg = 4.0`、`euler`、`normal`、SLG 层 `22`、`edit_format = "Moss-Image-Edit"`。
- **参数配置**：
  - `source_image`（必填，`image`）：待编辑底图文件名。
  - `edit_instruction`（必填，`string`）：建议采用 `只把 X 改成 Y，保持人物、脸部、姿势、背景和构图不变` 句式。

---

### 4.3 视频生成工作流（7 套，全部输出带原生立体声音轨 MP4 至 `output/video/`）

#### （7）`text2video_minimax_h3` — MiniMax H3 文生视频【已启用】
- **目录**：`workflows/text2video_minimax_h3/`
- **内置模型**：`minimax_h3_fl2va_pruned_int8_convrot` + `minimax_h3_fl2v_turbo_8step_v1.0` + `qwen3vl_32b_minimax_h3_nvfp4_awq` + 音视频双 VAE
- **固定设置**：`24 fps`、`res_multistep`、`simple`、`BasicGuider`（CFG=1）；时长按 `17k + 5` 帧网格自动对齐（5.0 秒 = 124 帧）。
- **参数配置**：
  - `positive_prompt`（必填，`string`）：同时描述画面主体动作、镜头运动以及对白/环境音效/配乐。
  - `aspect_ratio`（可选，`enum`，默认 `"16:9 (Widescreen)"`）：完整比例枚举值。
  - `megapixels`（可选，`number`，默认 `0.98`）：官方原生 768p（`1344×768`）。
  - `duration_seconds`（可选，`number`，默认 `5.0`）：支持 `5.0–15.0` 秒。
  - `enable_lightning_lora`（可选，`boolean`，默认 `true`）：`true` = 8 步高速采样；`false` = 20 步慢采。

#### （8）`image2video_first_frame_minimax_h3` — MiniMax H3 单图首帧生视频【已启用】
- **目录**：`workflows/image2video_first_frame_minimax_h3/`
- **适用场景**：将画布上已确认满意的静帧图片动起来，锁定开场构图与人物外观。
- **参数配置**：
  - `first_frame_image`（必填，`image`）：起始首帧图片文件名（对应 `<Picture 1>`）。
  - `positive_prompt`（必填，`string`）：描述首帧之后的动作变化、运镜推拉与声音。
  - `aspect_ratio`（可选，`enum`，默认 `"9:16 (Portrait Widescreen)"`）：**调用时务必传入与首帧图片一致的画幅比例**（横图传 `"16:9 (Widescreen)"`，方图传 `"1:1 (Square)"`），防止画面裁切变形。
  - `megapixels`（可选，`number`，默认 `0.98`）/ `duration_seconds`（默认 `5.0`）/ `enable_lightning_lora`（默认 `true`）。

#### （9）`image2video_first_last_frame_minimax_h3` — MiniMax H3 双图首尾帧生视频【已停用】
- **目录**：`workflows/image2video_first_last_frame_minimax_h3/`
- **适用场景**：给定镜头起始画面 `<Picture 1>` 与结束画面 `<Picture 2>`（如白昼转夜景、远景推近景、状态变化），生成受控过渡视频。
- **参数配置**：
  - `first_frame_image`（必填，`image`）：首帧文件名（`<Picture 1>`）。
  - `last_frame_image`（必填，`image`）：尾帧文件名（`<Picture 2>`）。
  - `positive_prompt`（必填，`string`）：描述 `<Picture 1>` 到 `<Picture 2>` 的过渡动作、光影演变与音效。
  - `aspect_ratio`（默认 `"1:1 (Square)"`，请与首尾帧比例一致）/ `megapixels`（默认 `0.98`）/ `duration_seconds`（默认 `5.0`）/ `enable_lightning_lora`（默认 `true`）。

#### （10）`ref2video_dual_minimax_h3_fl2va_turbo` — MiniMax H3 FL2VA 双图参考生视频 (Turbo)【已启用】
- **目录**：`workflows/ref2video_dual_minimax_h3_fl2va_turbo/`
- **适用场景**：不同于首尾帧锁死第一帧构图，本工作流提取两张参考图的主体语义特征（如 `<Picture 1>` 的人物 + `<Picture 2>` 的器物/场景），在新构图和新机位下生成互动视频，固定 8 步 Turbo 速度快。
- **参数配置**：
  - `reference_image_1`（必填，`image`）：第 1 张参考图文件名（`<Picture 1>`）。
  - `reference_image_2`（必填，`image`）：第 2 张参考图文件名（`<Picture 2>`）。
  - `positive_prompt`（必填，`string`）：明确用 `<Picture 1>` 与 `<Picture 2>` 说明各自角色与互动动作、运镜及音效。
  - `aspect_ratio`（默认 `"9:16 (Portrait Widescreen)"`）/ `megapixels`（默认 `0.98`）/ `duration_seconds`（默认 `5.0`）。

#### （11）`ref2video_minimax_h3_ref2va` — MiniMax H3 Ref2VA 多参考生视频【已停用】
- **目录**：`workflows/ref2video_minimax_h3_ref2va/`
- **适用场景**：支持 **1–4 张参考图**（如双角色互动 + 指定场景 + 指定道具），使用专用 `minimax_h3_ref2va` 权重与 `normal` 调度器，20 步高保真还原多主体一致性。
- **参数配置**：
  - `reference_image`（必填，`image`）：第 1 张参考图（`<Picture 1>`）。
  - `reference_image_2` ~ `reference_image_4`（可选，`image`）：第 2–4 张参考图（`<Picture 2>`~`<Picture 4>`），按顺序连续填写。
  - `positive_prompt`（必填，`string`）：用 `<Picture 1>`~`<Picture 4>` 指定各参考要素的职责与分镜动作。
  - `aspect_ratio`（默认 `"16:9 (Widescreen)"`）/ `megapixels`（默认 `0.98`）/ `duration_seconds`（默认 `5.0`）。
  - `enable_lightning_lora`（可选，`boolean`，默认 `false`）：默认走 20 步高保真；4 步 `v0.1` LoRA 仅作草稿快测。

#### （12）`ref2video_multimodal_minimax_h3_rf` — MiniMax H3 多图音频参考生视频【已停用】
- **目录**：`workflows/ref2video_multimodal_minimax_h3_rf/`
- **适用场景**：需要传入**参考音频**（参考音色、口播台词或背景鼓点节奏）配合 1–5 张参考图联合生成视频；采用 `minimax_h3_ref2va` + `EasyCache`（阈值 `0.15`，25 步 `normal`），需 ComfyUI 已装 `ComfyUI-KJNodes`。
- **参数配置**：
  - `reference_image_1`（必填，`image`）：主参考图（`<Picture 1>`，同时决定输出宽高比例）。
  - `reference_image_2` ~ `reference_image_5`（可选，`image`）：第 2–5 张参考图（`<Picture 2>`~`<Picture 5>`）。
  - `reference_audio_1` ~ `reference_audio_3`（可选，`audio`）：第 1–3 段参考音频文件名（`.wav`/`.mp3` 等，对应 `<Audio 1>`~`<Audio 3>`）。
  - `positive_prompt`（必填，`string`）：结合 `<Picture N>` 与 `<Audio N>` 描述动作与声画同步要求。
  - `duration_seconds`（默认 `5`）/ `max_size`（默认 `1024` 像素基准）/ `fps`（默认 `24.0`）。

#### （13）`ref2video_multiref_minimax_h3_rh` — MiniMax H3 开源版双图参考生视频 (RH)【已停用】
- **目录**：`workflows/ref2video_multiref_minimax_h3_rh/`
- **依赖限制**：依赖 `ComfyUI-RH-MiniMax-H3` 自定义节点及 `models/MiniMax-H3/` 独立权重目录（当前云端硬盘未装该目录，保持停用）。
- **参数配置**：`reference_image_1`（必填）、`reference_image_2`（必填）、`positive_prompt`（必填）、`aspect_ratio`（短比例枚举如 `"9:16"`、`"16:9"`，勿带括号后缀）、`duration_seconds`（默认 `8`）、`width`（默认 `736`）、`height`（默认 `1024`）。

#### （13b）`image_multiref_moss` / `ref2video_quad_minimax_h3_ref2va` / `ref2video_dual_minimax_h3_r2v`（阶段 P7 新增入库）
- **`image_multiref_moss`**（`workflows/image_multiref_moss/`）：支持 `reference_image_1`~`reference_image_4` 经 Qwen3.5 视觉解析驱动 MOSS-Image 5B 生成 `2.0 MP` 新图。
- **`ref2video_quad_minimax_h3_ref2va`**（`workflows/ref2video_quad_minimax_h3_ref2va/`）：具名四元素槽位 `character_a_image`（`<Picture 1>`）、`character_b_image`（`<Picture 2>`）、`scene_image`（`<Picture 3>`）、`prop_image`（`<Picture 4>`），调度器已校准为 `normal` 并经过 LoRA Switch。
- **`ref2video_dual_minimax_h3_r2v`**（`workflows/ref2video_dual_minimax_h3_r2v/`）：已修复原草稿中悬空的 `prompt`/`width`/`height`/`length` 连线并补齐 `reference_image_2` 槽位与 8 步 Turbo LoRA 步数。

---

### 4.4 视频超分工作流（1 套）

#### （14）`video_upscale_seedvr2_3b` — SeedVR2 3B 视频超分【已停用】
- **目录**：`workflows/video_upscale_seedvr2_3b/`
- **适用场景**：将已生成的 768p/480p 视频放大至 2K 级别并修复压缩噪点，保留原视频帧率与伴随音轨（纯 ComfyUI Core 原生节点，模型已安装，可随时启用）。
- **固定设置**：SeedVR2 单步扩散修复（`steps = 1, cfg = 1.0, euler, simple, denoise = 1.0`），VAE 时空分块编解码。
- **参数配置**：
  - `source_video`（必填，`video`）：画布或本地上传的视频文件名（如 `bp36AWJakl.mp4`）。
  - `scale_multiplier`（可选，`number`，默认 `2.0`）：放大倍率（768p × `2.0` = `2688×1536`；24GB 显存建议控制在 `1.5–2.0`）。
  - `split_latent`（可选，`boolean`，默认 `false`）：5–8 秒短视频保持 `false`；超过 8 秒的长视频设为 `true` 开启时间分块（已内置 8 帧重叠融合防闪帧）。
  - `trim_video`（默认 `false`）/ `trim_start_time`（`0.0`）/ `trim_duration`（`0.0`）：需要只截取其中一段超分时将 `trim_video` 设为 `true` 并指定起止秒数。
  - `color_correction_method`（可选，`enum`，默认 `"lab"`）：可选 `"lab"`、`"wavelet"`、`"adain"`、`"none"`，默认 `"lab"` 对齐原片色调防止偏色。

---

## 5. 硬件显存与运行耗时参考（L4 24GB 显存 + 云端硬盘）

1. **首次冷加载 vs 热态复跑**：模型权重存放在 Google Drive 云盘时，切换模型族后的首轮推理需从云盘读取 18–40 GB 权重，首轮耗时约 3–12 分钟；同模型族连续生图热态仅需 **90–190 秒**（4.0 MP），5 秒 768p 视频热态约 **8–9 分钟**。
2. **统一轻量编码器收益**：MiniMax H3 图像与视频工作流已统一指向 `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`（15.7 GB），可完整放入 24GB 显存避免 CPU Offload 卡顿，并在图像与视频工作流之间共享编码器缓存。
3. **日常开关组合建议**：
   - 海报与改字任务优先用 `SenseNova U1.6`；多图融合与连续分镜生视频优先用 `MiniMax H3` 家族。
   - 不常用的重型工作流在「设置 -> ComfyUI」保持关闭，减少 Agent 工具选择干扰。
