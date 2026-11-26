/** 程序说明：导演分镜时间轴可视化编排组件（P7-3：支持镜头上下排序、单镜起止秒裁剪、逐镜台词字幕自动换算时间轴、一键抽尾帧接力、剥离音轨、精装合片与分块超分）。 */
import { Button } from '@/components/ui/button'
import { apiFetch } from '@/lib/apiFetch'
import { eventBus } from '@/lib/event'
import {
  ArrowDown,
  ArrowUp,
  Clapperboard,
  ImagePlus,
  Music,
  Plus,
  Sparkles,
  X,
} from 'lucide-react'
import React, { useEffect, useState } from 'react'
import { toast } from 'sonner'

type TimelineShot = {
  id: string
  file: string
  trimStart: string
  trimEnd: string
  subtitle: string
}

type StudioDirectorTimelineProps = {
  canvasId: string
  canvasVideos: string[]
  canvasAudios?: string[]
  onDone?: () => void
}

function makeShot(file: string, defaultTrimEnd = '15.0'): TimelineShot {
  return {
    id: `${file}_${Math.random().toString(36).slice(2, 7)}`,
    file,
    trimStart: '0',
    trimEnd: defaultTrimEnd,
    subtitle: '',
  }
}

export const StudioDirectorTimeline: React.FC<StudioDirectorTimelineProps> = ({
  canvasId,
  canvasVideos,
  canvasAudios = [],
  onDone,
}) => {
  const [shots, setShots] = useState<TimelineShot[]>([])
  const [fadeSec, setFadeSec] = useState<string>('0.2')
  const [outroSec, setOutroSec] = useState<string>('0.6')
  const [introTitle, setIntroTitle] = useState<string>('')
  const [bgmAudio, setBgmAudio] = useState<string>('')
  const [audioDucking, setAudioDucking] = useState<boolean>(true)
  const [loudnorm, setLoudnorm] = useState<boolean>(true)
  const [burnSubtitles, setBurnSubtitles] = useState<boolean>(true)
  const [busyAction, setBusyAction] = useState<string>('')

  useEffect(() => {
    if (shots.length === 0 && canvasVideos.length > 0) {
      setShots(canvasVideos.slice(0, 6).map((vf) => makeShot(vf, '')))
    }
  }, [canvasVideos, shots.length])

  const moveShot = (index: number, delta: -1 | 1) => {
    const nextIdx = index + delta
    if (nextIdx < 0 || nextIdx >= shots.length) return
    setShots((prev) => {
      const copy = [...prev]
      const [moved] = copy.splice(index, 1)
      copy.splice(nextIdx, 0, moved)
      return copy
    })
  }

  const updateShot = (id: string, patch: Partial<TimelineShot>) => {
    setShots((prev) =>
      prev.map((item) => (item.id === id ? { ...item, ...patch } : item))
    )
  }

  const removeShot = (id: string) => {
    setShots((prev) => prev.filter((item) => item.id !== id))
  }

  const handleLoadAllCanvasVideos = () => {
    if (canvasVideos.length === 0) {
      toast.info('当前画布暂无视频元素')
      return
    }
    setShots(canvasVideos.map((vf) => makeShot(vf, '')))
  }

  const handleExtractTailFrameRelay = async (videoFile: string) => {
    setBusyAction(`frame_${videoFile}`)
    try {
      const resp = await apiFetch('/api/studio/extract_frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_file: videoFile,
          mode: 'last',
          place_on_canvas: true,
          canvas_id: canvasId,
        }),
      })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`)
      eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })
      eventBus.emit('Canvas::AddImagesToChat', [
        { fileId: body.file_id, width: body.width, height: body.height },
      ])
      eventBus.emit('Canvas::AddTextToChat', [
        `请以上一段视频尾帧 <Picture 1> (${body.file_id}) 作为首帧锚点，保持人物面容、服饰与场景光线一致，接力生成下一段分镜视频：`,
      ])
      toast.success(`已提取尾帧 ${body.file_id} 并填入接力对话`)
      onDone?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '提取尾帧失败')
    } finally {
      setBusyAction('')
    }
  }

  const handleExtractShotAudio = async (videoFile: string) => {
    setBusyAction(`audio_${videoFile}`)
    try {
      const resp = await apiFetch('/api/studio/extract_audio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_file: videoFile,
          normalize_loudness: true,
          canvas_id: canvasId,
        }),
      })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`)
      eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })
      toast.success(`已剥离音频卡片：${body.file_id}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '剥离音轨失败')
    } finally {
      setBusyAction('')
    }
  }

  const estimatedTotalSec = shots.reduce((acc, s) => {
    const st = Math.max(0, Number(s.trimStart) || 0)
    const ed = Number(s.trimEnd)
    const dur = Number.isFinite(ed) && ed > st ? ed - st : 15.0
    return acc + dur
  }, 0)

  const handleComposeTimeline = async () => {
    if (shots.length === 0) {
      toast.info('请先添加至少 1 段分镜视频到时间轴')
      return
    }
    setBusyAction('compose')
    try {
      let cursor = 0
      const clipEdits = shots.map((s) => {
        const st = Number(s.trimStart)
        const ed = Number(s.trimEnd)
        const cleanStart = Number.isFinite(st) && st > 0 ? st : null
        const cleanEnd =
          Number.isFinite(ed) && ed > (cleanStart || 0) ? ed : null
        return {
          file: s.file,
          trim_start: cleanStart,
          trim_end: cleanEnd,
        }
      })

      const subtitles: { start: number; end: number; text: string }[] = []
      for (const s of shots) {
        const st = Math.max(0, Number(s.trimStart) || 0)
        const ed = Number(s.trimEnd)
        const segDur = Number.isFinite(ed) && ed > st ? ed - st : 15.0
        if (s.subtitle.trim()) {
          subtitles.push({
            start: Number((cursor + 0.25).toFixed(2)),
            end: Number((cursor + Math.max(1.0, segDur - 0.25)).toFixed(2)),
            text: s.subtitle.trim(),
          })
        }
        cursor += segDur
      }

      const fadeVal = Number(fadeSec)
      const outroVal = Number(outroSec)
      const resp = await apiFetch('/api/studio/compose_video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_files: shots.map((s) => s.file),
          clip_edits: clipEdits,
          transition_fade_sec:
            Number.isFinite(fadeVal) && fadeVal >= 0 ? fadeVal : 0.2,
          preserve_clip_audio: true,
          bgm_audio: bgmAudio || null,
          enable_audio_ducking: audioDucking,
          normalize_audio_loudness: loudnorm,
          burn_subtitles: burnSubtitles && subtitles.length > 0,
          subtitles: subtitles.length > 0 ? subtitles : null,
          intro_title: introTitle.trim() || null,
          fade_out_outro_sec:
            Number.isFinite(outroVal) && outroVal >= 0 ? outroVal : 0,
          canvas_id: canvasId,
        }),
      })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`)
      eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })
      toast.success(
        `导演时间轴精装合片完成：${body.file_id}（${body.duration_sec}s）`
      )
      onDone?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '时间轴合片失败')
    } finally {
      setBusyAction('')
    }
  }

  const handleChunkedUpscaleLatest = async () => {
    const targetVideo = shots[shots.length - 1]?.file || canvasVideos[canvasVideos.length - 1]
    if (!targetVideo) {
      toast.info('请先在时间轴选择一段待超分视频')
      return
    }
    setBusyAction('upscale')
    try {
      const resp = await apiFetch('/api/studio/upscale_chunked', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_file: targetVideo,
          scale_multiplier: 2.0,
          canvas_id: canvasId,
        }),
      })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`)
      if (body.status === 'completed') {
        eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })
        toast.success(`2× 分块超分完成：${body.file_id}`)
        onDone?.()
      } else {
        toast.info(
          `超分已保存断点（${body.completed_chunks}/${body.total_chunks} 段），可在「云盘映射与清理」随时续跑`
        )
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '启动分块超分失败')
    } finally {
      setBusyAction('')
    }
  }

  return (
    <div className="space-y-2 rounded-lg border p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 font-semibold">
          <Clapperboard className="size-4 text-purple-600" aria-hidden="true" />
          <span>导演分镜时间轴 ({shots.length} 镜 · 约 {estimatedTotalSec.toFixed(1)}s)</span>
        </div>
        <Button
          size="sm"
          variant="outline"
          type="button"
          className="h-6 gap-1 px-2 text-[11px]"
          onClick={handleLoadAllCanvasVideos}
        >
          <Plus className="size-3" aria-hidden="true" />
          载入画布视频 ({canvasVideos.length})
        </Button>
      </div>

      <div className="max-h-44 space-y-1.5 overflow-y-auto rounded border bg-muted/20 p-2">
        {shots.length === 0 ? (
          <p className="py-4 text-center text-muted-foreground">
            当前画布暂无视频镜头，生成分镜视频后可在此编排顺序、裁剪秒数与绑定字幕
          </p>
        ) : (
          shots.map((shot, idx) => (
            <div
              key={shot.id}
              className="space-y-1.5 rounded border bg-background p-2"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-mono font-medium truncate">
                  #{idx + 1} {shot.file}
                </span>
                <div className="flex shrink-0 items-center gap-0.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busyAction !== ''}
                    title="提取本镜尾帧接力下一镜"
                    className="h-6 px-1.5 text-[10px]"
                    onClick={() => void handleExtractTailFrameRelay(shot.file)}
                  >
                    <ImagePlus className="mr-0.5 size-3 text-emerald-600" />
                    尾帧接力
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busyAction !== ''}
                    title="剥离独立音频卡"
                    className="h-6 px-1 text-[10px]"
                    onClick={() => void handleExtractShotAudio(shot.file)}
                  >
                    <Music className="size-3 text-sky-600" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={idx === 0}
                    aria-label="镜头上移"
                    className="h-6 px-1"
                    onClick={() => moveShot(idx, -1)}
                  >
                    <ArrowUp className="size-3" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={idx === shots.length - 1}
                    aria-label="镜头下移"
                    className="h-6 px-1"
                    onClick={() => moveShot(idx, 1)}
                  >
                    <ArrowDown className="size-3" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label="移出时间轴"
                    className="h-6 px-1 text-muted-foreground"
                    onClick={() => removeShot(shot.id)}
                  >
                    <X className="size-3" />
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-1.5">
                <input
                  type="number"
                  min="0"
                  step="0.5"
                  value={shot.trimStart}
                  onChange={(e) =>
                    updateShot(shot.id, { trimStart: e.target.value })
                  }
                  placeholder="起(s)"
                  aria-label={`第 ${idx + 1} 镜起始秒`}
                  className="h-6 rounded border bg-background px-1.5 text-[11px]"
                />
                <input
                  type="number"
                  min="0.5"
                  step="0.5"
                  value={shot.trimEnd}
                  onChange={(e) =>
                    updateShot(shot.id, { trimEnd: e.target.value })
                  }
                  placeholder="止(如15)"
                  aria-label={`第 ${idx + 1} 镜结束秒`}
                  className="h-6 rounded border bg-background px-1.5 text-[11px]"
                />
                <input
                  type="text"
                  value={shot.subtitle}
                  onChange={(e) =>
                    updateShot(shot.id, { subtitle: e.target.value })
                  }
                  placeholder="本镜叠加台词/字幕（可空）"
                  aria-label={`第 ${idx + 1} 镜台词字幕`}
                  className="col-span-2 h-6 rounded border bg-background px-2 text-[11px]"
                />
              </div>
            </div>
          ))
        )}
      </div>

      <div className="grid grid-cols-3 gap-1.5 pt-0.5">
        <input
          type="text"
          value={introTitle}
          onChange={(e) => setIntroTitle(e.target.value)}
          placeholder="片头标题（可空）"
          className="h-7 rounded border bg-background px-2 text-[11px]"
        />
        <input
          type="number"
          min="0"
          max="2"
          step="0.05"
          value={fadeSec}
          onChange={(e) => setFadeSec(e.target.value)}
          placeholder="转场(s)"
          title="切镜柔和转场秒数"
          className="h-7 rounded border bg-background px-2 text-[11px]"
        />
        <input
          type="number"
          min="0"
          max="5"
          step="0.2"
          value={outroSec}
          onChange={(e) => setOutroSec(e.target.value)}
          placeholder="片尾淡出(s)"
          title="片尾黑场淡出秒数"
          className="h-7 rounded border bg-background px-2 text-[11px]"
        />
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
        {canvasAudios.length > 0 && (
          <select
            value={bgmAudio}
            aria-label="选择背景配乐"
            onChange={(e) => setBgmAudio(e.target.value)}
            className="h-6 rounded border bg-background px-1.5 text-[11px] text-foreground"
          >
            <option value="">不叠加背景音乐</option>
            {canvasAudios.map((af) => (
              <option key={af} value={af}>
                配乐：{af}
              </option>
            ))}
          </select>
        )}
        {bgmAudio && (
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={audioDucking}
              onChange={(e) => setAudioDucking(e.target.checked)}
            />
            <span>人声自动闪避配乐</span>
          </label>
        )}
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={loudnorm}
            onChange={(e) => setLoudnorm(e.target.checked)}
          />
          <span>EBU R128 响度均衡</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={burnSubtitles}
            onChange={(e) => setBurnSubtitles(e.target.checked)}
          />
          <span>硬烧录镜头字幕</span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-2 pt-0.5">
        <Button
          size="sm"
          variant="secondary"
          type="button"
          disabled={busyAction !== '' || shots.length === 0}
          className="h-8 text-xs"
          onClick={() => void handleComposeTimeline()}
        >
          {busyAction === 'compose'
            ? 'ffmpeg 精装合片中…'
            : `合成精装总成片 (${shots.length})`}
        </Button>
        <Button
          size="sm"
          variant="outline"
          type="button"
          disabled={busyAction !== '' || (shots.length === 0 && canvasVideos.length === 0)}
          className="h-8 gap-1 text-xs"
          onClick={() => void handleChunkedUpscaleLatest()}
        >
          <Sparkles className="size-3.5 text-amber-500" aria-hidden="true" />
          <span>{busyAction === 'upscale' ? '分块超分中…' : '末段分块 2× 超分'}</span>
        </Button>
      </div>
    </div>
  )
}

export default StudioDirectorTimeline
