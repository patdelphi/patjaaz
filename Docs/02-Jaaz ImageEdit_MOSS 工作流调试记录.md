# Jaaz ImageEdit_MOSS 工作流调试记录

更新日期：2026-11-22

## 工作流信息

- Jaaz 工作流名：ImageEdit_MOSS
- ComfyUI 工作流文件：图像编辑_MOSS-Image.json
- 类型：单张底图指令编辑
- 模型：MOSS-Image SFT int8、MOSS Image Edit rank-64 LoRA、Qwen 3.5 9B W4A8 GPTQ、FLUX.2 small VAE
- ComfyUI 输出前缀：moss/moss_image_edit

## Jaaz 输入映射

- source_image：必填，映射至 LoadImage 节点 8 的 image。调用时传 Jaaz 中实际上传或选中的图片文件。
- edit_instruction：必填，映射至 positive Text Encode 节点 39 的 prompt。只描述要改动的部分，并明确需要保留的细节。
- 负面提示词仍使用工作流固定值。
- 两个 Text Encode 节点的 edit_format 固定为 Moss-Image-Edit，image_strength 固定为 1。
- 工作流示例底图和示例编辑指令已在 Jaaz 配置中清空，防止输入缺失时复用示例内容。

## 保留的模型参数

- Image Scale To Total Pixels：1.0 MP，resolution_steps 16，Lanczos；由预处理后的底图尺寸生成 latent，保持底图比例。
- KSampler：30 步、CFG 4、Euler、normal、denoise 1。
- Skip Layer Guidance：single layer 22，范围 0 至 1。
- 以上参数与 Comfy-Org 官方图像编辑模板一致。
- ComfyUI 版本要求：0.43.0 或更新版本。
- 官方模板：https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_moss_image_edit.json

## 实测结果

- 测试输入：Jaaz 本地文件 server/user_data/files/zHi1jbuVSe.png，橘猫插画。
- 编辑指令：Change only the cat's irises to a clear blue. Keep its orange fur, expression, pose, window, background, lighting, and composition unchanged.
- ComfyUI 任务完成，用时约 53.12 秒；输出尺寸 1024×1024。
- ComfyUI 输出文件：moss/moss_image_edit_00001_.png。
- Jaaz 本地缓存：server/user_data/files/30EtNk3Wv5.png，855,849 字节。
- 测试画布 ID：3add4018-96c6-4438-90bb-b12ac03ad90e；画布数据中记录 1 张图片。
- 已打开结果图核对，猫的虹膜变成蓝色，主体和背景保持稳定。

## 验证边界

本次通过 Jaaz 动态工作流工具执行，覆盖了参数映射、图片上传、ComfyUI 推理、结果下载和画布写回。没有通过自然语言聊天测试模型自动选择工作流或自动识别附件。

## 配置备份

优化前的 Jaaz 数据库备份：
server/user_data/ImageEdit_MOSS-before-optimization-20261122150513Z.sqlite

## 相关文档

- ComfyUI 工作流使用说明：H:\我的云端硬盘\comfyui\user\default\workflows\工作流使用说明.md
