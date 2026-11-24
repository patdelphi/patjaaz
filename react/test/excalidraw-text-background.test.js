import {
  patchCanvasDev,
  patchCanvasProd,
  patchSvgDev,
  patchSvgProd,
} from "../scripts/patch-excalidraw-text-background.mjs"

describe("Excalidraw text background patch", () => {
  it("adds a background fill to the development canvas renderer", () => {
    const source = "context.save();\n        context.font = getFontString(element);"
    const patched = patchCanvasDev(source)
    expect(patched).toContain("context.fillRect(0, 0, element.width, element.height)")
    expect(patchCanvasDev(patched)).toBe(patched)
  })

  it("adds a background fill to the production canvas renderer", () => {
    const source = 'n.canvas.setAttribute("dir",i?"rtl":"ltr"),n.save(),n.font=Ee(e),n.fillStyle=e.strokeColor,n.textAlign=e.textAlign;'
    const patched = patchCanvasProd(source)
    expect(patched).toContain("n.fillRect(0,0,e.width,e.height)")
    expect(patchCanvasProd(patched)).toBe(patched)
  })

  it("adds a background rectangle to the development SVG renderer", () => {
    const source = '        const node = svgRoot.ownerDocument.createElementNS(SVG_NS, "g");'
    const patched = patchSvgDev(source)
    expect(patched).toContain('createElementNS(SVG_NS, "rect")')
    expect(patchSvgDev(patched)).toBe(patched)
  })

  it("adds a background rectangle to the production SVG renderer", () => {
    const source = "let w=e.text.replace"
    const patched = patchSvgProd(source)
    expect(patched).toContain('createElementNS(re,"rect")')
    expect(patchSvgProd(patched)).toBe(patched)
  })
})
