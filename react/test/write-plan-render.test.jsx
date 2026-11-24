// 验证 write_plan 计划卡片面对异常模型参数时不会崩溃。
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createInstance } from 'i18next'
import { beforeAll, describe, expect, it } from 'vitest'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import WritePlanToolCall from '../src/components/chat/Message/WritePlanToolcall'

let i18n

beforeAll(async () => {
  i18n = createInstance()
  await i18n.use(initReactI18next).init({
    lng: 'en',
    resources: { en: { chat: { plan: { title: 'Plan' } } } },
    ns: ['chat'],
    defaultNS: 'chat',
  })
})

function renderPlan(args) {
  return renderToStaticMarkup(
    createElement(
      I18nextProvider,
      { i18n },
      createElement(WritePlanToolCall, { args })
    )
  )
}

describe('WritePlanToolCall rendering', () => {
  it('renders safely when steps is not an array', () => {
    expect(() => renderPlan('{"steps":"not-an-array"}')).not.toThrow()
    expect(renderPlan('{"steps":{"title":"Inspect"}}')).toContain('Plan')
  })

  it('renders valid steps', () => {
    const markup = renderPlan(
      JSON.stringify({ steps: [{ title: 'Inspect', description: 'Check logs' }] })
    )
    expect(markup).toContain('Inspect')
    expect(markup).toContain('Check logs')
  })
})