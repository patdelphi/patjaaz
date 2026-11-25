import { CanvasData, Message, Session } from '@/types/types'
import { ToolInfo } from '@/api/model'
import { apiFetch } from '@/lib/apiFetch'
import { waitForPendingCanvasSaves } from '@/lib/canvasSaveQueue'

export type ListCanvasesResponse = {
  id: string
  name: string
  description?: string
  thumbnail?: string
  created_at: string
}

export async function listCanvases(): Promise<ListCanvasesResponse[]> {
  const response = await fetch('/api/canvas/list')
  return await response.json()
}

export async function createCanvas(data: {
  name: string
  canvas_id: string
  messages: Message[]
  session_id: string
  text_model: {
    provider: string
    model: string
    url: string
  }
  tool_list: ToolInfo[]

  system_prompt: string
}): Promise<{ id: string }> {
  const response = await fetch('/api/canvas/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return await response.json()
}

export async function getCanvas(
  id: string
): Promise<{ data: CanvasData; name: string; sessions: Session[] }> {
  await waitForPendingCanvasSaves(id)
  const response = await apiFetch(`/api/canvas/${id}`)
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => null)
    const detail =
      typeof errorPayload?.detail === 'string'
        ? errorPayload.detail
        : response.statusText || `HTTP ${response.status}`
    throw new Error(`Failed to load canvas (${response.status}): ${detail}`)
  }
  return await response.json()
}

export async function saveCanvas(
  id: string,
  payload: {
    data: CanvasData
    thumbnail: string
  }
): Promise<void> {
  const response = await fetch(`/api/canvas/${id}/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(
      'Failed to save canvas (' +
        response.status +
        '): ' +
        (errorText || response.statusText)
    )
  }
  await response.json()
}

export async function renameCanvas(id: string, name: string): Promise<void> {
  const response = await fetch(`/api/canvas/${id}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return await response.json()
}

export async function deleteCanvas(id: string): Promise<void> {
  const response = await fetch(`/api/canvas/${id}/delete`, {
    method: 'DELETE',
  })
  return await response.json()
}

export type CanvasElementOp = {
  op: 'upsert' | 'delete' | 'reorder'
  id?: string
  element?: Record<string, unknown>
  order_ids?: string[]
}

export async function applyCanvasOps(
  id: string,
  payload: {
    ops: CanvasElementOp[]
    files?: Record<string, unknown>
    appState?: Record<string, unknown>
    thumbnail?: string
  }
): Promise<{ id: string; applied: number }> {
  const response = await apiFetch(`/api/canvas/${id}/ops`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Failed to apply canvas ops (${response.status}): ${errorText}`)
  }
  return await response.json()
}

export type CanvasSnapshotSummary = {
  id: string
  canvas_id: string
  note: string
  element_count: number
  thumbnail?: string
  created_at: string
}

export async function listCanvasSnapshots(id: string): Promise<CanvasSnapshotSummary[]> {
  const response = await apiFetch(`/api/canvas/${id}/snapshots`)
  if (!response.ok) return []
  return await response.json()
}

export async function createCanvasSnapshot(
  id: string,
  note = ''
): Promise<CanvasSnapshotSummary> {
  const response = await apiFetch(`/api/canvas/${id}/snapshots`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  })
  if (!response.ok) {
    throw new Error(`Failed to create snapshot (${response.status})`)
  }
  return await response.json()
}

export async function restoreCanvasSnapshot(
  id: string,
  snapId: string
): Promise<{ id: string; snapshot_id: string; data: CanvasData }> {
  const response = await apiFetch(`/api/canvas/${id}/snapshots/${snapId}/restore`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error(`Failed to restore snapshot (${response.status})`)
  }
  return await response.json()
}
