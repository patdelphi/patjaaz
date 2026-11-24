/** 程序说明：通用文本大模型提供商设置面板，支持 OpenAI / Anthropic / Gemini / Compatible 四类协议切换、模型能力配置与一键测试连通。 */
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { PROVIDER_NAME_MAPPING } from '@/constants'
import {
  DEFAULT_PROTOCOL_URLS,
  inferProviderProtocol,
  LLMProtocol,
  PROTOCOL_OPTIONS,
} from '@/lib/llmProtocol'
import { LLMConfig } from '@/types/types'
import { Activity, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import AddModelsList, { ModelConfigEntry } from './AddModelsList'

interface CommonSettingProps {
  providerKey: string
  config: LLMConfig
  onConfigChange: (key: string, newConfig: LLMConfig) => void
  onDeleteProvider?: (providerKey: string) => void
}

export default function CommonSetting({
  providerKey,
  config,
  onConfigChange,
  onDeleteProvider,
}: CommonSettingProps) {
  const { t } = useTranslation()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    ok: boolean
    message: string
  } | null>(null)

  const provider = PROVIDER_NAME_MAPPING[providerKey] || {
    name:
      providerKey.charAt(0).toUpperCase() +
      providerKey.slice(1).replace(/_/g, ' '),
    icon: 'https://openai.com/favicon.ico',
  }

  const isCustomProvider = config.is_custom
  const effectiveProtocol = inferProviderProtocol(providerKey, config)

  const handleChange = (field: keyof LLMConfig, value: string | number) => {
    onConfigChange(providerKey, {
      ...config,
      [field]: value,
    })
  }

  const handleProtocolChange = (nextProtocol: LLMProtocol) => {
    const suggestedUrl = DEFAULT_PROTOCOL_URLS[nextProtocol]
    onConfigChange(providerKey, {
      ...config,
      protocol: nextProtocol,
      url: config.url?.trim() ? config.url : suggestedUrl,
    })
  }

  const handleModelsChange = (models: Record<string, ModelConfigEntry>) => {
    onConfigChange(providerKey, {
      ...config,
      models,
    })
  }

  const handleDelete = () => {
    if (onDeleteProvider && isCustomProvider) {
      onDeleteProvider(providerKey)
    }
  }

  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const resp = await fetch('/api/settings/test_llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: providerKey,
          protocol: effectiveProtocol,
          url: config.url || '',
          api_key: config.api_key || '',
          model: Object.keys(config.models || {})[0] || '',
        }),
      })
      const data = await resp.json()
      const ok = Boolean(data.ok)
      const message = String(data.message || '')
      setTestResult({ ok, message })
      if (ok) {
        toast.success(message)
      } else {
        toast.error(message)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setTestResult({ ok: false, message })
      toast.error(`测试失败: ${message}`)
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Provider Header */}
      <div className="flex flex-wrap items-center gap-2">
        <img
          src={provider.icon}
          alt={provider.name}
          className="w-10 h-10 rounded-full"
        />
        <p className="font-bold text-2xl w-fit">{provider.name}</p>
        <Badge variant="outline">{effectiveProtocol}</Badge>
        {isCustomProvider && <span>✨ Custom Provider</span>}

        <div className="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={testing}
            onClick={handleTestConnection}
          >
            <Activity className={`h-4 w-4 mr-1 ${testing ? 'animate-pulse' : ''}`} />
            {testing ? '测试中...' : '测试连接'}
          </Button>
          {isCustomProvider && onDeleteProvider && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleDelete}
              className="text-red-600 hover:text-red-700 hover:bg-red-50"
            >
              <Trash2 className="h-4 w-4 mr-1" />
              {t('settings:provider.delete')}
            </Button>
          )}
        </div>
      </div>

      {testResult && (
        <div
          className={`text-xs px-3 py-2 rounded border ${
            testResult.ok
              ? 'bg-green-50 border-green-200 text-green-700'
              : 'bg-red-50 border-red-200 text-red-700'
          }`}
        >
          {testResult.message}
        </div>
      )}

      {/* Protocol Selector */}
      {providerKey !== 'ollama' && (
        <div className="space-y-2">
          <Label htmlFor={`${providerKey}-protocol`}>接入协议</Label>
          <Select
            value={effectiveProtocol}
            onValueChange={(val) => handleProtocolChange(val as LLMProtocol)}
          >
            <SelectTrigger id={`${providerKey}-protocol`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROTOCOL_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* API URL Input */}
      <div className="space-y-2">
        <Label htmlFor={`${providerKey}-url`}>
          {t('settings:provider.apiUrl')}
        </Label>
        <Input
          id={`${providerKey}-url`}
          placeholder={t('settings:provider.apiUrlPlaceholder')}
          value={config.url ?? ''}
          onChange={(e) => handleChange('url', e.target.value)}
          className="w-full"
        />
      </div>

      {/* API Key Input */}
      <div className="space-y-2">
        <Label htmlFor={`${providerKey}-apiKey`}>
          {t('settings:provider.apiKey')}
        </Label>
        <Input
          id={`${providerKey}-apiKey`}
          type="password"
          placeholder={t('settings:provider.apiKeyPlaceholder')}
          value={config.api_key ?? ''}
          onChange={(e) => handleChange('api_key', e.target.value)}
          className="w-full"
        />
        <p className="text-xs text-gray-500">
          {t('settings:provider.apiKeyDescription')}
        </p>
      </div>

      {/* Models Configuration */}
      {providerKey !== 'ollama' && (
        <div className="space-y-2">
          <AddModelsList
            models={config.models || {}}
            onChange={handleModelsChange}
            label={t('settings:models.title')}
          />
        </div>
      )}

      {/* Max Tokens Input */}
      <div className="space-y-2">
        <Label htmlFor={`${providerKey}-maxTokens`}>
          {t('settings:provider.maxTokens')}
        </Label>
        <Input
          id={`${providerKey}-maxTokens`}
          type="number"
          placeholder={t('settings:provider.maxTokensPlaceholder')}
          value={config.max_tokens ?? 8192}
          onChange={(e) =>
            handleChange('max_tokens', parseInt(e.target.value, 10) || 8192)
          }
          className="w-full"
        />
        <p className="text-xs text-gray-500">
          {t('settings:provider.maxTokensDescription')}
        </p>
      </div>
    </div>
  )
}
