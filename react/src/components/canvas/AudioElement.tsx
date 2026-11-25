/** 程序说明：画布内嵌音频播放卡片组件，顶部支持按住直接拖拽移动画布元素，底部提供原生音频控制条与下载按钮。 */
import React, { useId } from 'react'
import { Download, Music } from 'lucide-react'
import { extractApiFilename } from '@/lib/canvasMediaNormalize'
import { cn } from '@/lib/utils'

interface AudioElementProps {
  src: string
  title?: string
  width?: number
  height?: number
  className?: string
}

export const AudioElement: React.FC<AudioElementProps> = ({
  src,
  title,
  width = 360,
  height = 108,
  className,
}) => {
  const titleId = useId()
  const intWidth = Math.max(220, Math.round(width))
  const intHeight = Math.max(88, Math.round(height))
  const displayTitle = title || extractApiFilename(src) || 'Audio Clip'

  return (
    <figure
      className={cn(
        'relative flex flex-col justify-between overflow-hidden rounded-lg border border-white/10 bg-zinc-900/95 px-3.5 py-2.5 text-zinc-100 select-none shadow-md',
        className
      )}
      style={{ width: intWidth, height: intHeight }}
    >
      {/* 顶部标题区不拦截指针事件，方便直接在卡片上半区按住拖拽或框选 */}
      <div className="pointer-events-none flex items-center gap-2 min-w-0">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-emerald-500/20 text-emerald-400">
          <Music className="size-3.5" aria-hidden="true" />
        </span>
        <figcaption
          id={titleId}
          className="truncate text-xs font-medium text-zinc-100"
        >
          {displayTitle}
        </figcaption>
      </div>

      {/* 底部控制区开启独立指针事件；遵循 lazy-load-video-and-audio 规范保留 controls 与 preload="metadata" */}
      <div
        className="pointer-events-auto flex items-center gap-2 pt-1"
        style={{ pointerEvents: 'auto' }}
        onPointerDown={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        <audio
          controls
          preload="metadata"
          {...({ loading: 'lazy' } as Record<string, unknown>)}
          src={src}
          aria-labelledby={titleId}
          className="h-8 flex-1 min-w-0"
        />
        <a
          href={src}
          download
          aria-label={`Download ${displayTitle}`}
          onClick={(e) => e.stopPropagation()}
          className="flex min-h-7 min-w-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-zinc-100 hover:bg-white/25 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        >
          <Download className="size-3.5" aria-hidden="true" />
        </a>
      </div>
    </figure>
  )
}
