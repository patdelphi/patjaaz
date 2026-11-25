/** 程序说明：画布顶部图层管理（显隐/锁定/层级排序，C7）与历史版本快照回退面板（C10）。 */
import {
  CanvasSnapshotSummary,
  createCanvasSnapshot,
  listCanvasSnapshots,
  restoreCanvasSnapshot,
} from '@/api/canvas'
import { Button } from '@/components/ui/button'
import { useCanvas } from '@/contexts/canvas'
import { normalizeCanvasElementsForScene } from '@/lib/canvasMediaNormalize'
import { mutateSceneElements } from '@/lib/excalidrawMutation'
import type { OrderedExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import {
  ArrowDown,
  ArrowUp,
  Eye,
  EyeOff,
  History,
  Layers,
  Lock,
  Plus,
  RotateCcw,
  Unlock,
} from 'lucide-react'
import React, { useEffect, useId, useRef, useState } from 'react'
import { toast } from 'sonner'

type CanvasLayersAndSnapshotsDrawerProps = {
  canvasId: string
}

export const CanvasLayersAndSnapshotsDrawer: React.FC<
  CanvasLayersAndSnapshotsDrawerProps
> = ({ canvasId }) => {
  const { excalidrawAPI } = useCanvas()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  const [tab, setTab] = useState<'layers' | 'snapshots'>('layers')
  const [elements, setElements] = useState<OrderedExcalidrawElement[]>([])
  const [snapshots, setSnapshots] = useState<CanvasSnapshotSummary[]>([])
  const [snapNote, setSnapNote] = useState<string>('')
  const [busy, setBusy] = useState<boolean>(false)

  const refreshLayers = () => {
    if (!excalidrawAPI) return
    const active = excalidrawAPI
      .getSceneElements()
      .filter((el) => !el.isDeleted)
    setElements([...active].reverse())
  }

  const refreshSnapshots = async () => {
    try {
      const list = await listCanvasSnapshots(canvasId)
      setSnapshots(list)
    } catch {
      setSnapshots([])
    }
  }

  const openModal = (initialTab: 'layers' | 'snapshots') => {
    setTab(initialTab)
    refreshLayers()
    void refreshSnapshots()
    const dlg = dialogRef.current
    if (dlg && !dlg.open) {
      dlg.showModal()
    }
  }

  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    const onClose = () => {
      dlg.returnValue = ''
    }
    dlg.addEventListener('close', onClose)
    return () => dlg.removeEventListener('close', onClose)
  }, [])

  const toggleVisibility = (targetId: string) => {
    if (!excalidrawAPI) return
    mutateSceneElements(excalidrawAPI, (el) => {
      if (el.id !== targetId) return el
      const cd = (el.customData || {}) as Record<string, unknown>
      const isHidden = Boolean(cd.jaazHidden) || el.opacity === 0
      return {
        ...el,
        opacity: isHidden ? 100 : 0,
        customData: { ...cd, jaazHidden: !isHidden },
      }
    })
    refreshLayers()
  }

  const toggleLock = (targetId: string) => {
    if (!excalidrawAPI) return
    mutateSceneElements(excalidrawAPI, (el) =>
      el.id === targetId ? { ...el, locked: !el.locked } : el
    )
    refreshLayers()
  }

  const moveLayerOrder = (targetId: string, direction: 'up' | 'down') => {
    if (!excalidrawAPI) return
    const all = [...excalidrawAPI.getSceneElementsIncludingDeleted()]
    const idx = all.findIndex((e) => e.id === targetId)
    if (idx < 0) return
    const swapIdx = direction === 'up' ? idx + 1 : idx - 1
    if (swapIdx < 0 || swapIdx >= all.length) return
    const tmp = all[idx]
    all[idx] = all[swapIdx]
    all[swapIdx] = tmp
    excalidrawAPI.updateScene({ elements: all })
    refreshLayers()
  }

  const focusLayer = (target: OrderedExcalidrawElement) => {
    if (!excalidrawAPI) return
    excalidrawAPI.updateScene({
      appState: { selectedElementIds: { [target.id]: true } },
    })
    excalidrawAPI.scrollToContent(target, { animate: true })
  }

  const handleCreateSnapshot = async () => {
    setBusy(true)
    try {
      await createCanvasSnapshot(canvasId, snapNote)
      setSnapNote('')
      await refreshSnapshots()
      toast.success('已保存当前画布快照')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '创建快照失败')
    } finally {
      setBusy(false)
    }
  }

  const handleRestoreSnapshot = async (snapId: string) => {
    if (!excalidrawAPI) return
    setBusy(true)
    try {
      const res = await restoreCanvasSnapshot(canvasId, snapId)
      const restoredFiles = res.data?.files || {}
      if (Object.keys(restoredFiles).length > 0) {
        excalidrawAPI.addFiles(Object.values(restoredFiles))
      }
      const normalized = normalizeCanvasElementsForScene(
        (res.data?.elements || []) as unknown as ReadonlyArray<{
          id: string
          [key: string]: unknown
        }>,
        restoredFiles
      ) as unknown as OrderedExcalidrawElement[]
      excalidrawAPI.updateScene({ elements: normalized })
      refreshLayers()
      toast.success('已回退恢复到所选快照版本')
      dialogRef.current?.close()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '恢复快照失败')
    } finally {
      setBusy(false)
    }
  }

  const describeElement = (el: OrderedExcalidrawElement): string => {
    if (el.type === 'frame') return `画框 · ${el.name || el.id.slice(0, 8)}`
    if (el.type === 'text') return `文本 · ${(el.text || '').slice(0, 22)}`
    if (el.type === 'image') return `图像 · ${el.id.slice(0, 10)}`
    if (el.type === 'embeddable') return `音视频 · ${el.id.slice(0, 10)}`
    return `${el.type} · ${el.id.slice(0, 8)}`
  }

  return (
    <>
      <div className="inline-flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1 px-2.5 text-xs"
          onClick={() => openModal('layers')}
        >
          <Layers className="size-3.5" aria-hidden="true" />
          <span>图层</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1 px-2.5 text-xs"
          onClick={() => openModal('snapshots')}
        >
          <History className="size-3.5" aria-hidden="true" />
          <span>快照</span>
        </Button>
      </div>

      <dialog
        ref={dialogRef}
        aria-labelledby={titleId}
        className="jaaz-native-modal rounded-xl border bg-background p-5 text-foreground shadow-2xl max-w-xl w-[92vw]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between border-b pb-2.5">
            <div className="flex items-center gap-2">
              <h1 id={titleId} className="text-base font-semibold">
                {tab === 'layers' ? '画布图层管理' : '画布版本快照'}
              </h1>
              <div className="ml-2 inline-flex rounded-md border p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => {
                    setTab('layers')
                    refreshLayers()
                  }}
                  className={`rounded px-2.5 py-1 ${tab === 'layers' ? 'bg-primary text-primary-foreground' : ''}`}
                >
                  图层 ({elements.length})
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setTab('snapshots')
                    void refreshSnapshots()
                  }}
                  className={`rounded px-2.5 py-1 ${tab === 'snapshots' ? 'bg-primary text-primary-foreground' : ''}`}
                >
                  快照 ({snapshots.length})
                </button>
              </div>
            </div>
            <form method="dialog">
              <Button variant="ghost" size="sm" type="submit">
                关闭
              </Button>
            </form>
          </div>

          {tab === 'layers' ? (
            <div className="max-h-[56vh] space-y-1 overflow-y-auto pr-1">
              {elements.length === 0 ? (
                <p className="py-8 text-center text-xs text-muted-foreground">当前画布暂无元素</p>
              ) : (
                elements.slice(0, 120).map((el) => {
                  const hidden =
                    Boolean((el.customData as Record<string, unknown> | undefined)?.jaazHidden) ||
                    el.opacity === 0
                  return (
                    <div
                      key={el.id}
                      className="flex items-center justify-between rounded-md border px-2.5 py-1.5 text-xs hover:bg-muted/50"
                    >
                      <button
                        type="button"
                        onClick={() => focusLayer(el)}
                        className="truncate text-left font-medium flex-1 mr-2"
                      >
                        {describeElement(el)}
                      </button>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          aria-label="上移一层"
                          onClick={() => moveLayerOrder(el.id, 'up')}
                        >
                          <ArrowUp className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          aria-label="下移一层"
                          onClick={() => moveLayerOrder(el.id, 'down')}
                        >
                          <ArrowDown className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          aria-label={hidden ? '显示图层' : '隐藏图层'}
                          onClick={() => toggleVisibility(el.id)}
                        >
                          {hidden ? <EyeOff className="size-3.5 text-muted-foreground" /> : <Eye className="size-3.5" />}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 w-6 p-0"
                          aria-label={el.locked ? '解锁图层' : '锁定图层'}
                          onClick={() => toggleLock(el.id)}
                        >
                          {el.locked ? <Lock className="size-3.5 text-amber-500" /> : <Unlock className="size-3.5" />}
                        </Button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={snapNote}
                  onChange={(e) => setSnapNote(e.target.value)}
                  placeholder="可选备注（如：双图融合改图定稿前）"
                  className="h-8 flex-1 rounded-md border bg-background px-2.5 text-xs"
                />
                <Button
                  size="sm"
                  className="h-8 gap-1 text-xs"
                  disabled={busy}
                  onClick={() => void handleCreateSnapshot()}
                >
                  <Plus className="size-3.5" />
                  新建快照
                </Button>
              </div>
              <div className="max-h-[48vh] space-y-1.5 overflow-y-auto pr-1">
                {snapshots.length === 0 ? (
                  <p className="py-8 text-center text-xs text-muted-foreground">暂无已保存快照</p>
                ) : (
                  snapshots.map((snap) => (
                    <div
                      key={snap.id}
                      className="flex items-center justify-between rounded-md border p-2.5 text-xs"
                    >
                      <div>
                        <div className="font-medium">
                          {snap.note || `快照 ${snap.id.slice(0, 10)}`}
                        </div>
                        <div className="text-muted-foreground mt-0.5">
                          {snap.created_at} · {snap.element_count} 个元素
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1 text-xs"
                        disabled={busy}
                        onClick={() => void handleRestoreSnapshot(snap.id)}
                      >
                        <RotateCcw className="size-3" />
                        恢复此版
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </dialog>
    </>
  )
}

export default CanvasLayersAndSnapshotsDrawer
