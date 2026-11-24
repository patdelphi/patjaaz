/* 程序说明：保留旧脚本导出入口并转发至统一的 Excalidraw 0.18.1 补丁模块。 */
export {
  applyExcalidrawPatches,
  applyExcalidrawTextBackgroundPatch,
  patchArrowDev,
  patchArrowProd,
  patchCanvasDev,
  patchCanvasProd,
  patchSvgDev,
  patchSvgProd,
} from "./patch-excalidraw.mjs"
