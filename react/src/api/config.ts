import { apiFetch } from '@/lib/apiFetch'
import { LLMConfig } from '@/types/types'

export async function getConfigExists(): Promise<{ exists: boolean }> {
  const response = await apiFetch('/api/config/exists')
  return await response.json()
}

export async function getConfig(): Promise<{ [key: string]: LLMConfig }> {
  const response = await apiFetch('/api/config')
  return await response.json()
}

export async function updateConfig(config: {
  [key: string]: LLMConfig
}): Promise<{ status: string; message: string }> {
  const response = await apiFetch('/api/config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  })
  return await response.json()
}
