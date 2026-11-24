/** 程序说明：定义底部画布工具栏支持的 Excalidraw 工具类型、对应图标与快捷键映射。 */
import { ToolType as ExcalidrawToolType } from '@excalidraw/excalidraw/types'
import {
  ArrowUpRight,
  Circle,
  Diamond,
  Eraser,
  Frame,
  Hand,
  Image,
  Link,
  Minus,
  MousePointer2,
  Pencil,
  Sparkles,
  Square,
  Type,
} from 'lucide-react'
import React from 'react'

export type ToolType = Extract<
  ExcalidrawToolType,
  | 'hand'
  | 'selection'
  | 'rectangle'
  | 'diamond'
  | 'ellipse'
  | 'arrow'
  | 'line'
  | 'freedraw'
  | 'text'
  | 'image'
  | 'embeddable'
  | 'frame'
  | 'eraser'
  | 'laser'
>

const icons: Record<ToolType, React.ComponentType<{ className?: string }>> = {
  hand: Hand,
  selection: MousePointer2,
  rectangle: Square,
  diamond: Diamond,
  ellipse: Circle,
  arrow: ArrowUpRight,
  line: Minus,
  freedraw: Pencil,
  text: Type,
  image: Image,
  embeddable: Link,
  frame: Frame,
  eraser: Eraser,
  laser: Sparkles,
}

export const toolShortcuts: Record<ToolType, string> = {
  hand: 'H',
  selection: 'V',
  rectangle: 'R',
  diamond: 'D',
  ellipse: 'O',
  arrow: 'A',
  line: 'L',
  freedraw: 'P',
  text: 'T',
  image: '9',
  embeddable: '',
  frame: 'F',
  eraser: 'E',
  laser: 'K',
}

export default icons
