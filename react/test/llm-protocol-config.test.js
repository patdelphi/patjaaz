// M1 开放文本模型三协议推断与能力标签归一化回归测试。
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PROTOCOL_URLS,
  inferProviderProtocol,
  normalizeModelCapabilities,
} from '../src/lib/llmProtocol'

describe('llmProtocol helpers', () => {
  it('infers openai, anthropic, google, and openai-compatible protocols accurately', () => {
    expect(inferProviderProtocol('openai')).toBe('openai')
    expect(inferProviderProtocol('anthropic')).toBe('anthropic')
    expect(
      inferProviderProtocol('my_claude', { url: 'https://api.anthropic.com' })
    ).toBe('anthropic')
    expect(inferProviderProtocol('google')).toBe('google')
    expect(
      inferProviderProtocol('gemini_relay', {
        url: 'https://generativelanguage.googleapis.com/v1beta',
      })
    ).toBe('google')
    expect(
      inferProviderProtocol('deepseek', { url: 'https://api.deepseek.com/v1/' })
    ).toBe('openai-compatible')
    expect(
      inferProviderProtocol('custom', {
        protocol: 'google',
        url: 'https://proxy.example.com',
      })
    ).toBe('google')
  })

  it('provides sensible default URLs and normalizes capabilities', () => {
    expect(DEFAULT_PROTOCOL_URLS.anthropic).toBe('https://api.anthropic.com')
    expect(DEFAULT_PROTOCOL_URLS.google).toBe(
      'https://generativelanguage.googleapis.com'
    )
    expect(normalizeModelCapabilities({ vision: true, thinking: true })).toEqual({
      vision: true,
      tools: true,
      thinking: true,
    })
  })
})
