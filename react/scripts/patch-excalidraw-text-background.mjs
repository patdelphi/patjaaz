/* 程序说明：为 Excalidraw 0.18.1 的文字元素补上画布与 SVG 导出底色渲染。 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const markers = {
  canvasDev: "JAaz text background: canvas dev",
  svgDev: "JAaz text background: svg dev",
  canvasProd: "JAaz text background: canvas prod",
  svgProd: "JAaz text background: svg prod",
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
  const anchor = "context.save();\n        context.font = getFontString(element);"
  const replacement = [
    "context.save();",
    "        /* JAaz text background: canvas dev */",
    "        // 先绘制文字底色，再绘制文字内容。",
    "        if (element.backgroundColor && element.backgroundColor !== \"transparent\") {",
    "          context.fillStyle = element.backgroundColor;",
    "          context.fillRect(0, 0, element.width, element.height);",
    "        }",
    "        context.font = getFontString(element);",
  ].join("\n")
  return replaceOnce(source, anchor, replacement, markers.canvasDev)
}

export function patchCanvasProd(source) {
  const anchor = "n.canvas.setAttribute(\"dir\",i?\"rtl\":\"ltr\"),n.save(),n.font=Ee(e),n.fillStyle=e.strokeColor,n.textAlign=e.textAlign;"
  const replacement = "n.canvas.setAttribute(\"dir\",i?\"rtl\":\"ltr\"),n.save(),/* JAaz text background: canvas prod */e.backgroundColor&&e.backgroundColor!==\"transparent\"&&(n.fillStyle=e.backgroundColor,n.fillRect(0,0,e.width,e.height)),n.font=Ee(e),n.fillStyle=e.strokeColor,n.textAlign=e.textAlign;"
  return replaceOnce(source, anchor, replacement, markers.canvasProd)
}

export function patchSvgDev(source) {
  const anchor = "        const node = svgRoot.ownerDocument.createElementNS(SVG_NS, \"g\");"
  const replacement = [
    anchor,
    "        /* JAaz text background: svg dev */",
    "        // SVG 导出时为文字元素添加同一块底色。",
    "        if (element.backgroundColor && element.backgroundColor !== \"transparent\") {",
    "          const background = svgRoot.ownerDocument.createElementNS(SVG_NS, \"rect\");",
    "          background.setAttribute(\"width\", String(element.width));",
    "          background.setAttribute(\"height\", String(element.height));",
    "          background.setAttribute(\"fill\", element.backgroundColor);",
    "          background.setAttribute(\"stroke\", \"none\");",
    "          node.appendChild(background);",
    "        }",
  ].join("\n")
  return replaceOnce(source, anchor, replacement, markers.svgDev)
}

export function patchSvgProd(source) {
  const anchor = "let w=e.text.replace"
  const replacement = [
    "/* JAaz text background: svg prod */",
    "if(e.backgroundColor&&e.backgroundColor!==\"transparent\"){let p=r.ownerDocument.createElementNS(re,\"rect\");p.setAttribute(\"width\",String(e.width));p.setAttribute(\"height\",String(e.height));p.setAttribute(\"fill\",e.backgroundColor);p.setAttribute(\"stroke\",\"none\");y.appendChild(p)}",
    anchor,
  ].join("")
  return replaceOnce(source, anchor, replacement, markers.svgProd)
}

function patchBundle(folder, canvasPatch, canvasMarker, canvasAnchor, svgPatch, svgMarker, svgAnchor) {
  const files = readdirSync(folder)
    .filter((file) => file.endsWith(".js"))
    .map((file) => join(folder, file))

  const findTarget = (marker, anchor) =>
    files.find((file) => {
      const source = readFileSync(file, "utf8")
      return source.includes(marker) || source.includes(anchor)
    })

  const canvasFile = findTarget(canvasMarker, canvasAnchor)
  if (!canvasFile) throw new Error("Unable to locate the Excalidraw canvas text renderer")
  const canvasSource = readFileSync(canvasFile, "utf8")
  const patchedCanvas = canvasPatch(canvasSource)
  if (patchedCanvas !== canvasSource) writeFileSync(canvasFile, patchedCanvas, "utf8")

  const svgFile = findTarget(svgMarker, svgAnchor)
  if (!svgFile) throw new Error("Unable to locate the Excalidraw SVG text renderer")
  const svgSource = readFileSync(svgFile, "utf8")
  const patchedSvg = svgPatch(svgSource)
  if (patchedSvg !== svgSource) writeFileSync(svgFile, patchedSvg, "utf8")

  if (!readFileSync(canvasFile, "utf8").includes(canvasMarker)) {
    throw new Error("Excalidraw canvas text background patch was not applied")
  }
  if (!readFileSync(svgFile, "utf8").includes(svgMarker)) {
    throw new Error("Excalidraw SVG text background patch was not applied")
  }
}

export function applyExcalidrawTextBackgroundPatch(packageDir) {
  const packageJson = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"))
  if (packageJson.version !== "0.18.1") {
    throw new Error("This local patch targets @excalidraw/excalidraw 0.18.1; found " + packageJson.version)
  }

  patchBundle(
    join(packageDir, "dist/dev"),
    patchCanvasDev,
    markers.canvasDev,
    "context.save();\n        context.font = getFontString(element);",
    patchSvgDev,
    markers.svgDev,
    "        const node = svgRoot.ownerDocument.createElementNS(SVG_NS, \"g\");",
  )
  patchBundle(
    join(packageDir, "dist/prod"),
    patchCanvasProd,
    markers.canvasProd,
    "n.canvas.setAttribute(\"dir\",i?\"rtl\":\"ltr\"),n.save(),n.font=Ee(e),n.fillStyle=e.strokeColor,n.textAlign=e.textAlign;",
    patchSvgProd,
    markers.svgProd,
    "let w=e.text.replace",
  )
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : ""
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    const reactDir = resolve(dirname(fileURLToPath(import.meta.url)), "..")
    const packageDir = join(reactDir, "node_modules/@excalidraw/excalidraw")
    applyExcalidrawTextBackgroundPatch(packageDir)
    console.log("Applied Jaaz text background patch to Excalidraw 0.18.1")
  } catch (error) {
    console.error("Failed to patch Excalidraw text background:", error)
    process.exitCode = 1
  }
}
