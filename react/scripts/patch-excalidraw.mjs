/* 程序说明：统一为 Excalidraw 0.18.1 的开发与生产构建应用文字底色与粗箭头渲染/裁剪/虚线补丁。 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const markers = {
  canvasDev: "JAaz text background: canvas dev",
  svgDev: "JAaz text background: svg dev",
  canvasProd: "JAaz text background: canvas prod",
  svgProd: "JAaz text background: svg prod",
  arrowSizeDev: "JAaz arrow size: dev",
  arrowAngleDev: "JAaz arrow angle: dev",
  canvasPaddingDev: "JAaz canvas padding: dev",
  dashArrayDev: "JAaz dash array: dev",
  arrowSizeProd: "JAaz arrow size: prod",
  arrowAngleProd: "JAaz arrow angle: prod",
  canvasPaddingProd: "JAaz canvas padding: prod",
  dashArrayProd: "JAaz dash array: prod",
}

const ANCHORS = {
  canvasDev: "context.save();\n        context.font = getFontString(element);",
  svgDev: '        const node = svgRoot.ownerDocument.createElementNS(SVG_NS, "g");',
  canvasProd: 'n.canvas.setAttribute("dir",i?"rtl":"ltr"),n.save(),n.font=Ee(e),n.fillStyle=e.strokeColor,n.textAlign=e.textAlign;',
  svgProd: "let w=e.text.replace",
  arrowSizeDev: "const size = getArrowheadSize(arrowhead);",
  arrowAngleDev: "const angle = getArrowheadAngle(arrowhead);",
  canvasPaddingDev: [
    "var getCanvasPadding = (element) => {",
    "  switch (element.type) {",
    '    case "freedraw":',
    "      return element.strokeWidth * 12;",
    '    case "text":',
    "      return element.fontSize / 2;",
    "    default:",
    "      return 20;",
    "  }",
    "};",
  ].join("\n"),
  dashArrayDev: [
    "var getDashArrayDashed = (strokeWidth) => [8, 8 + strokeWidth];",
    "var getDashArrayDotted = (strokeWidth) => [1.5, 6 + strokeWidth];",
  ].join("\n"),
  arrowSizeProd: "w=km(r),I=0;",
  arrowAngleProd: 'let N=Zm(r);if(r==="crowfoot_many"',
  canvasPaddingProd:
    'ri=e=>{switch(e.type){case"freedraw":return e.strokeWidth*12;case"text":return e.fontSize/2;default:return 20}}',
  dashArrayProd: "var Cm=e=>[8,8+e],k1=e=>[1.5,6+e];",
}

/** 根据线宽计算粗箭头头部等比缩放倍率（strokeWidth <= 4 时保持原生尺寸）。 */
export function computeArrowheadScale(strokeWidth) {
  return strokeWidth > 4 ? 1 + (strokeWidth - 4) * 0.15 : 1
}

/** 粗线条开放式箭头半角随线宽适度张开，避免两侧翼贴入粗杆内部（封顶 30 度）。 */
export function computeArrowheadAngle(arrowhead, baseAngle, strokeWidth) {
  return arrowhead === "arrow" && strokeWidth > 4
    ? Math.min(30, baseAngle + (strokeWidth - 4) * 0.6)
    : baseAngle
}

/** 动态计算离屏缓存与导出的四边安全留白，避免粗箭头头部和描边被原生 20px 硬裁剪。 */
export function computeCanvasPadding(element) {
  switch (element.type) {
    case "freedraw":
      return element.strokeWidth * 12
    case "text":
      return element.fontSize / 2
    case "arrow":
      return Math.max(20, element.strokeWidth * 6)
    case "line":
      return Math.max(20, element.strokeWidth * 3)
    default:
      return Math.max(20, element.strokeWidth * 2 + 12)
  }
}

/** 粗线条虚线随线宽放大实线段与间隔，避免圆端虚线粘连成实线。 */
export function computeDashArrayDashed(strokeWidth) {
  return strokeWidth > 4
    ? [Math.max(8, strokeWidth * 2.5), Math.max(8 + strokeWidth, strokeWidth * 2)]
    : [8, 8 + strokeWidth]
}

/** 粗线条点线随线宽放大点距与线长比例。 */
export function computeDashArrayDotted(strokeWidth) {
  return strokeWidth > 4
    ? [Math.max(1.5, strokeWidth * 0.6), Math.max(6 + strokeWidth, strokeWidth * 1.8)]
    : [1.5, 6 + strokeWidth]
}

function replaceOnce(source, anchor, replacement, marker) {
  if (source.includes(marker)) return source
  const index = source.indexOf(anchor)
  if (index < 0) throw new Error("Excalidraw renderer anchor was not found: " + marker)
  if (source.indexOf(anchor, index + anchor.length) >= 0) {
    throw new Error("Excalidraw renderer anchor is ambiguous: " + marker)
  }
  return source.slice(0, index) + replacement + source.slice(index + anchor.length)
}

export function patchCanvasDev(source) {
  const replacement = [
    "context.save();",
    `        /* ${markers.canvasDev} */`,
    "        // 先绘制文字底色，再绘制文字内容。",
    '        if (element.backgroundColor && element.backgroundColor !== "transparent") {',
    "          context.fillStyle = element.backgroundColor;",
    "          context.fillRect(0, 0, element.width, element.height);",
    "        }",
    "        context.font = getFontString(element);",
  ].join("\n")
  return replaceOnce(source, ANCHORS.canvasDev, replacement, markers.canvasDev)
}

export function patchCanvasProd(source) {
  const replacement =
    `n.canvas.setAttribute("dir",i?"rtl":"ltr"),n.save(),/* ${markers.canvasProd} */` +
    'e.backgroundColor&&e.backgroundColor!=="transparent"&&(n.fillStyle=e.backgroundColor,n.fillRect(0,0,e.width,e.height)),n.font=Ee(e),n.fillStyle=e.strokeColor,n.textAlign=e.textAlign;'
  return replaceOnce(source, ANCHORS.canvasProd, replacement, markers.canvasProd)
}

export function patchSvgDev(source) {
  const replacement = [
    ANCHORS.svgDev,
    `        /* ${markers.svgDev} */`,
    "        // SVG 导出时为文字元素添加同一块底色。",
    '        if (element.backgroundColor && element.backgroundColor !== "transparent") {',
    '          const background = svgRoot.ownerDocument.createElementNS(SVG_NS, "rect");',
    '          background.setAttribute("width", String(element.width));',
    '          background.setAttribute("height", String(element.height));',
    '          background.setAttribute("fill", element.backgroundColor);',
    '          background.setAttribute("stroke", "none");',
    "          node.appendChild(background);",
    "        }",
  ].join("\n")
  return replaceOnce(source, ANCHORS.svgDev, replacement, markers.svgDev)
}

export function patchSvgProd(source) {
  const replacement = [
    `/* ${markers.svgProd} */`,
    'if(e.backgroundColor&&e.backgroundColor!=="transparent"){let p=r.ownerDocument.createElementNS(re,"rect");p.setAttribute("width",String(e.width));p.setAttribute("height",String(e.height));p.setAttribute("fill",e.backgroundColor);p.setAttribute("stroke","none");y.appendChild(p)}',
    ANCHORS.svgProd,
  ].join("")
  return replaceOnce(source, ANCHORS.svgProd, replacement, markers.svgProd)
}

export function patchArrowDev(source) {
  let out = replaceOnce(
    source,
    ANCHORS.arrowSizeDev,
    `/* ${markers.arrowSizeDev} */ const size = getArrowheadSize(arrowhead) * (element.strokeWidth > 4 ? 1 + (element.strokeWidth - 4) * 0.15 : 1);`,
    markers.arrowSizeDev
  )
  out = replaceOnce(
    out,
    ANCHORS.arrowAngleDev,
    `/* ${markers.arrowAngleDev} */ const angle = arrowhead === "arrow" && element.strokeWidth > 4 ? Math.min(30, getArrowheadAngle(arrowhead) + (element.strokeWidth - 4) * 0.6) : getArrowheadAngle(arrowhead);`,
    markers.arrowAngleDev
  )
  out = replaceOnce(
    out,
    ANCHORS.canvasPaddingDev,
    [
      "var getCanvasPadding = (element) => {",
      `  /* ${markers.canvasPaddingDev} */`,
      "  switch (element.type) {",
      '    case "freedraw":',
      "      return element.strokeWidth * 12;",
      '    case "text":',
      "      return element.fontSize / 2;",
      '    case "arrow":',
      "      return Math.max(20, element.strokeWidth * 6);",
      '    case "line":',
      "      return Math.max(20, element.strokeWidth * 3);",
      "    default:",
      "      return Math.max(20, element.strokeWidth * 2 + 12);",
      "  }",
      "};",
    ].join("\n"),
    markers.canvasPaddingDev
  )
  out = replaceOnce(
    out,
    ANCHORS.dashArrayDev,
    [
      `/* ${markers.dashArrayDev} */`,
      "var getDashArrayDashed = (strokeWidth) => strokeWidth > 4 ? [Math.max(8, strokeWidth * 2.5), Math.max(8 + strokeWidth, strokeWidth * 2)] : [8, 8 + strokeWidth];",
      "var getDashArrayDotted = (strokeWidth) => strokeWidth > 4 ? [Math.max(1.5, strokeWidth * 0.6), Math.max(6 + strokeWidth, strokeWidth * 1.8)] : [1.5, 6 + strokeWidth];",
    ].join("\n"),
    markers.dashArrayDev
  )
  return out
}

export function patchArrowProd(source) {
  let out = replaceOnce(
    source,
    ANCHORS.arrowSizeProd,
    `/* ${markers.arrowSizeProd} */w=km(r)*(e.strokeWidth>4?1+(e.strokeWidth-4)*.15:1),I=0;`,
    markers.arrowSizeProd
  )
  out = replaceOnce(
    out,
    ANCHORS.arrowAngleProd,
    `/* ${markers.arrowAngleProd} */let N=r==="arrow"&&e.strokeWidth>4?Math.min(30,Zm(r)+(e.strokeWidth-4)*.6):Zm(r);if(r==="crowfoot_many"`,
    markers.arrowAngleProd
  )
  out = replaceOnce(
    out,
    ANCHORS.canvasPaddingProd,
    `ri=e=>{/* ${markers.canvasPaddingProd} */switch(e.type){case"freedraw":return e.strokeWidth*12;case"text":return e.fontSize/2;case"arrow":return Math.max(20,e.strokeWidth*6);case"line":return Math.max(20,e.strokeWidth*3);default:return Math.max(20,e.strokeWidth*2+12)}}`,
    markers.canvasPaddingProd
  )
  out = replaceOnce(
    out,
    ANCHORS.dashArrayProd,
    `/* ${markers.dashArrayProd} */var Cm=e=>e>4?[Math.max(8,e*2.5),Math.max(8+e,e*2)]:[8,8+e],k1=e=>e>4?[Math.max(1.5,e*.6),Math.max(6+e,e*1.8)]:[1.5,6+e];`,
    markers.dashArrayProd
  )
  return out
}

function patchTargetInDir(folder, label, marker, anchor, patchFn) {
  const files = readdirSync(folder)
    .filter((file) => file.endsWith(".js"))
    .map((file) => join(folder, file))

  const targetFile = files.find((file) => {
    const source = readFileSync(file, "utf8")
    return source.includes(marker) || source.includes(anchor)
  })
  if (!targetFile) {
    throw new Error(`Unable to locate Excalidraw target for ${label} in ${folder}`)
  }

  const original = readFileSync(targetFile, "utf8")
  const patched = patchFn(original)
  if (patched !== original) {
    writeFileSync(targetFile, patched, "utf8")
  }
  if (!readFileSync(targetFile, "utf8").includes(marker)) {
    throw new Error(`Excalidraw patch verification failed for ${label}`)
  }
}

export function applyExcalidrawPatches(packageDir) {
  const packageJson = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"))
  if (packageJson.version !== "0.18.1") {
    throw new Error(
      "This local patch targets @excalidraw/excalidraw 0.18.1; found " + packageJson.version
    )
  }

  const devDir = join(packageDir, "dist/dev")
  const prodDir = join(packageDir, "dist/prod")

  patchTargetInDir(devDir, "canvasDev", markers.canvasDev, ANCHORS.canvasDev, patchCanvasDev)
  patchTargetInDir(devDir, "svgDev", markers.svgDev, ANCHORS.svgDev, patchSvgDev)
  patchTargetInDir(devDir, "arrowDev", markers.arrowSizeDev, ANCHORS.arrowSizeDev, patchArrowDev)

  patchTargetInDir(prodDir, "canvasProd", markers.canvasProd, ANCHORS.canvasProd, patchCanvasProd)
  patchTargetInDir(prodDir, "svgProd", markers.svgProd, ANCHORS.svgProd, patchSvgProd)
  patchTargetInDir(prodDir, "arrowProd", markers.arrowSizeProd, ANCHORS.arrowSizeProd, patchArrowProd)
}

export { applyExcalidrawPatches as applyExcalidrawTextBackgroundPatch }

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : ""
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    const reactDir = resolve(dirname(fileURLToPath(import.meta.url)), "..")
    const packageDir = join(reactDir, "node_modules/@excalidraw/excalidraw")
    applyExcalidrawPatches(packageDir)
    console.log("Applied Jaaz Excalidraw 0.18.1 patches (text background + thick arrows)")
  } catch (error) {
    console.error("Failed to patch Excalidraw:", error)
    process.exitCode = 1
  }
}
