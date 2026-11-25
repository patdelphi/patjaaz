/** 程序说明：画布内嵌视频播放组件，支持画面区直接拖拽选中及底部控制栏播放、有声/静音切换、进度拖拽与下载。 */
import React, { useState, useRef, useEffect } from 'react'
import { Download, Pause, Play, Volume2, VolumeX } from 'lucide-react'
import { VideoPreview } from '@/components/ui/video-player'
import { cn } from '@/lib/utils'

interface VideoElementProps {
    src: string
    poster?: string
    duration?: number
    autoPlay?: boolean
    loop?: boolean
    muted?: boolean
    className?: string
    width?: number
    height?: number
    isPreview?: boolean
    onClick?: () => void
    onTimeUpdate?: (currentTime: number, duration: number) => void
    onEnded?: () => void
}

function formatSeconds(sec: number): string {
    if (!Number.isFinite(sec) || sec < 0) return '0:00'
    const total = Math.floor(sec)
    const m = Math.floor(total / 60)
    const s = total % 60
    return `${m}:${String(s).padStart(2, '0')}`
}

export const VideoElement: React.FC<VideoElementProps> = ({
    src,
    poster,
    duration,
    autoPlay = false,
    loop = true,
    muted = true,
    className,
    width = 320,
    height = 180,
    isPreview = false,
    onClick,
    onTimeUpdate,
    onEnded,
}) => {
    const [isPlaying, setIsPlaying] = useState(false)
    const [isMuted, setIsMuted] = useState(muted)
    const [userStarted, setUserStarted] = useState(false)
    const [isHovered, setIsHovered] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [totalDuration, setTotalDuration] = useState<number>(duration || 0)
    const videoRef = useRef<HTMLVideoElement>(null)

    if (isPreview) {
        return (
            <VideoPreview
                src={src}
                poster={poster}
                className={className}
                width={width}
                height={height}
                onClick={() => {
                    onClick?.()
                }}
            />
        )
    }

    const prefersReducedMotion = () =>
        typeof window !== 'undefined' &&
        Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)

    const handleMouseEnter = () => {
        setIsHovered(true)
        const video = videoRef.current
        if (video && !userStarted && !isPlaying && !prefersReducedMotion()) {
            void video.play().then(() => setIsPlaying(true)).catch(() => {})
        }
    }

    const handleMouseLeave = () => {
        setIsHovered(false)
        const video = videoRef.current
        // 用户主动播放或开启声音后，移出鼠标不打断播放、也不重置进度
        if (video && !userStarted && isMuted && isPlaying) {
            video.pause()
            setIsPlaying(false)
        }
    }

    const togglePlay = (e: React.MouseEvent) => {
        e.stopPropagation()
        const video = videoRef.current
        if (!video) return
        if (isPlaying) {
            video.pause()
            setIsPlaying(false)
            setUserStarted(false)
        } else {
            setUserStarted(true)
            void video.play().then(() => setIsPlaying(true)).catch(() => {})
        }
        onClick?.()
    }

    const toggleMute = (e: React.MouseEvent) => {
        e.stopPropagation()
        const video = videoRef.current
        if (!video) return
        const nextMuted = !isMuted
        video.muted = nextMuted
        setIsMuted(nextMuted)
        if (!nextMuted && !isPlaying) {
            setUserStarted(true)
            void video.play().then(() => setIsPlaying(true)).catch(() => {})
        }
    }

    const handleScrub = (e: React.ChangeEvent<HTMLInputElement>) => {
        e.stopPropagation()
        const nextTime = Number(e.target.value)
        const video = videoRef.current
        if (video && Number.isFinite(nextTime)) {
            video.currentTime = nextTime
            setCurrentTime(nextTime)
        }
    }

    useEffect(() => {
        const video = videoRef.current
        if (!video) return

        const handleLoadedMetadata = () => {
            if (Number.isFinite(video.duration) && video.duration > 0) {
                setTotalDuration(video.duration)
            }
        }
        const handleEnded = () => {
            if (!loop) {
                setIsPlaying(false)
                setUserStarted(false)
            }
            onEnded?.()
        }
        const handleTimeUpdate = () => {
            setCurrentTime(video.currentTime)
            if (Number.isFinite(video.duration) && video.duration > 0) {
                setTotalDuration(video.duration)
                onTimeUpdate?.(video.currentTime, video.duration)
            }
        }

        video.addEventListener('loadedmetadata', handleLoadedMetadata)
        video.addEventListener('ended', handleEnded)
        video.addEventListener('timeupdate', handleTimeUpdate)
        return () => {
            video.removeEventListener('loadedmetadata', handleLoadedMetadata)
            video.removeEventListener('ended', handleEnded)
            video.removeEventListener('timeupdate', handleTimeUpdate)
        }
    }, [loop, onEnded, onTimeUpdate])

    const intWidth = Math.max(1, Math.round(width))
    const intHeight = Math.max(1, Math.round(height))

    // 主体不拦截 pointerDown，确保在视频画面内可直接按住拖拽移动或选中画布元素；底部控制栏独立响应播放与音量控制
    return (
        <div
            className={cn('group relative select-none overflow-hidden rounded-md', className)}
            style={{ width: intWidth, height: intHeight }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        >
            <video
                ref={videoRef}
                src={src}
                poster={poster}
                width={intWidth}
                height={intHeight}
                autoPlay={autoPlay && !prefersReducedMotion()}
                loop={loop}
                muted={isMuted}
                preload="metadata"
                {...({ loading: 'lazy' } as Record<string, unknown>)}
                className="w-full h-full object-cover pointer-events-none"
                playsInline
            />

            <div
                className={cn(
                    'pointer-events-auto absolute inset-x-0 bottom-0 z-20 flex items-center gap-2 bg-gradient-to-t from-black/80 via-black/45 to-transparent px-2.5 py-2 text-white transition-opacity duration-150',
                    isHovered || !isPlaying || !isMuted ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                )}
                style={{ pointerEvents: 'auto' }}
                onPointerDown={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
            >
                <button
                    type="button"
                    aria-label={isPlaying ? 'Pause video' : 'Play video'}
                    onClick={togglePlay}
                    className="flex min-h-7 min-w-7 items-center justify-center rounded-full bg-white/15 hover:bg-white/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                >
                    {isPlaying ? (
                        <Pause className="size-3.5" aria-hidden="true" />
                    ) : (
                        <Play className="size-3.5" aria-hidden="true" />
                    )}
                </button>

                <button
                    type="button"
                    aria-label="Mute video audio"
                    aria-pressed={isMuted}
                    onClick={toggleMute}
                    className="flex min-h-7 min-w-7 items-center justify-center rounded-full bg-white/15 hover:bg-white/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                >
                    {isMuted ? (
                        <VolumeX className="size-3.5" aria-hidden="true" />
                    ) : (
                        <Volume2 className="size-3.5" aria-hidden="true" />
                    )}
                </button>

                <input
                    type="range"
                    aria-label="Video timeline"
                    min={0}
                    max={totalDuration > 0 ? totalDuration : 1}
                    step={0.05}
                    value={Math.min(currentTime, totalDuration > 0 ? totalDuration : 1)}
                    onChange={handleScrub}
                    className="h-1.5 flex-1 cursor-pointer accent-white"
                />

                <span className="text-[11px] tabular-nums opacity-90">
                    {formatSeconds(currentTime)} / {formatSeconds(totalDuration)}
                </span>

                <a
                    href={src}
                    download
                    aria-label="Download video"
                    onClick={(e) => e.stopPropagation()}
                    className="flex min-h-7 min-w-7 items-center justify-center rounded-full bg-white/15 hover:bg-white/30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                >
                    <Download className="size-3.5" aria-hidden="true" />
                </a>
            </div>
        </div>
    )
}

// Canvas-specific video component that integrates with Excalidraw elements
export const CanvasVideoElement: React.FC<{
    elementId: string
    src: string
    x: number
    y: number
    width: number
    height: number
    duration?: number
    isSelected?: boolean
    onSelect?: (e?: React.MouseEvent) => void
    onDelete?: () => void
    onResize?: (direction: string, e: React.MouseEvent) => void
    onPaste?: (videoData: any) => void
}> = ({
    elementId,
    src,
    x: _x,
    y: _y,
    width,
    height,
    duration,
    isSelected = false,
    onSelect: _onSelect,
    onDelete,
    onResize,
    onPaste: _onPaste,

}) => {
        // Focus the element when selected to ensure keyboard events work
        useEffect(() => {
            if (isSelected) {
                // Small delay to ensure the element is rendered
                setTimeout(() => {
                    const element = document.querySelector(`[data-video-id="${elementId}"]`) as HTMLElement
                    if (element) {
                        element.focus()
                    }
                }, 10)
            }
        }, [isSelected, elementId])

        return (
            <div
                className={cn(
                    'relative w-full h-full cursor-pointer transition-all',
                    isSelected && 'ring-2 ring-blue-500'
                )}
                tabIndex={0}
                data-video-id={elementId}
                onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    console.log('🎯 CanvasVideoElement div clicked')

                    // 获取元素的绝对坐标和尺寸信息
                    const rect = e.currentTarget.getBoundingClientRect()
                    const elementInfo = {
                        elementId,
                        absolutePosition: {
                            x: rect.left,
                            y: rect.top,
                            right: rect.right,
                            bottom: rect.bottom
                        },
                        dimensions: {
                            width: rect.width,
                            height: rect.height
                        },
                    }

                    console.log('📍 Element position and size info:', elementInfo)


                }}
                onKeyDown={(e) => {
                    if (!isSelected) return

                    // Delete functionality
                    if (e.key === 'Delete' && onDelete) {
                        e.preventDefault()
                        e.stopPropagation()
                        console.log('🗑️ Delete key pressed on video element')
                        onDelete()
                    }

                    // TODO: Copy/Paste functionality disabled due to coordinate system confusion
                    // The current implementation mixes screen coordinates with canvas coordinates,
                    // causing incorrect positioning when pasting videos. Need to fix coordinate
                    // transformation between screen space and canvas space before re-enabling.

                    // Copy functionality (Ctrl+C) - DISABLED
                    // if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
                    //     e.preventDefault()
                    //     e.stopPropagation()

                    //     // 获取当前元素的位置和尺寸信息
                    //     const rect = e.currentTarget.getBoundingClientRect()
                    //     const elementInfo = {
                    //         elementId,
                    //         absolutePosition: {
                    //             x: rect.left,
                    //             y: rect.top,
                    //             right: rect.right,
                    //             bottom: rect.bottom
                    //         },
                    //         dimensions: {
                    //             width: rect.width,
                    //             height: rect.height
                    //         },
                    //     }

                    //     const videoData = {
                    //         type: 'video-element',
                    //         elementId,
                    //         src,
                    //         x: elementInfo.absolutePosition.x,
                    //         y: elementInfo.absolutePosition.y,
                    //         width: elementInfo.dimensions.width,
                    //         height: elementInfo.dimensions.height,
                    //         duration
                    //     }
                    //     navigator.clipboard.writeText(JSON.stringify(videoData))
                    //     console.log('📋 Video element copied to clipboard', videoData)
                    // }

                    // Paste functionality (Ctrl+V) - DISABLED
                    // if ((e.ctrlKey || e.metaKey) && e.key === 'v' && onPaste) {
                    //     e.preventDefault()
                    //     e.stopPropagation()
                    //     navigator.clipboard.readText().then(text => {
                    //         try {
                    //             const videoData = JSON.parse(text)
                    //             if (videoData.type === 'video-element') {
                    //                 console.log('📋 Pasting video element from clipboard')
                    //                 onPaste(videoData)
                    //             }
                    //         } catch (error) {
                    //             console.log('📋 Clipboard does not contain valid video data')
                    //         }
                    //     }).catch(error => {
                    //         console.error('📋 Failed to read clipboard:', error)
                    //     })
                    // }
                }}
            >
                <VideoElement
                    src={src}
                    width={width}
                    height={height}
                    duration={duration}
                    isPreview={false}
                    muted={true}
                    autoPlay={false}
                    onClick={() => {
                        console.log('🎬 VideoElement clicked')
                        // Don't call onSelect again - already handled by parent div
                    }}
                />

                {/* Selection border and resize handles */}
                {isSelected && (
                    <>
                        {/* Four corner resize handles */}
                        <div
                            className="absolute -top-1 -left-1 w-3 h-3 bg-blue-500 border border-white rounded-sm cursor-nw-resize z-20"
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onResize?.('nw', e)
                            }}
                            title="Resize"
                        />
                        <div
                            className="absolute -top-1 -right-1 w-3 h-3 bg-blue-500 border border-white rounded-sm cursor-ne-resize z-20"
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onResize?.('ne', e)
                            }}
                            title="Resize"
                        />
                        <div
                            className="absolute -bottom-1 -left-1 w-3 h-3 bg-blue-500 border border-white rounded-sm cursor-sw-resize z-20"
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onResize?.('sw', e)
                            }}
                            title="Resize"
                        />
                        <div
                            className="absolute -bottom-1 -right-1 w-3 h-3 bg-blue-500 border border-white rounded-sm cursor-se-resize z-20"
                            onMouseDown={(e) => {
                                e.stopPropagation()
                                onResize?.('se', e)
                            }}
                            title="Resize"
                        />


                    </>
                )}
            </div>
        )
    }

export default VideoElement