/** 程序说明：新增开放大模型提供商弹窗，支持按三协议模板（OpenAI/Claude/Gemini/Compatible）快速配置与能力标记。 */
import CommonDialogContent from '@/components/common/DialogContent'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import {
  Dialog,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DEFAULT_PROTOCOL_URLS,
  LLMProtocol,
  PROTOCOL_OPTIONS,
} from '@/lib/llmProtocol'
import { LLMConfig } from '@/types/types'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import AddModelsList, { ModelConfigEntry } from './AddModelsList'

interface AddProviderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (providerKey: string, config: LLMConfig) => void
}

const PROVIDER_OPTIONS = [
  {
    value: 'anthropic',
    label: 'Claude (Anthropic)',
    data: {
      protocol: 'anthropic' as LLMProtocol,
      apiUrl: 'https://api.anthropic.com',
      models: {
        'claude-sonnet-4-20250514': {
          type: 'text' as const,
          capabilities: { vision: true, tools: true, thinking: true },
        },
        'claude-3-7-sonnet-latest': {
          type: 'text' as const,
          capabilities: { vision: true, tools: true, thinking: true },
        },
      },
    },
  },
  {
    value: 'google',
    label: 'Google Gemini',
    data: {
      protocol: 'google' as LLMProtocol,
      apiUrl: 'https://generativelanguage.googleapis.com',
      models: {
        'gemini-2.5-flash': {
          type: 'text' as const,
          capabilities: { vision: true, tools: true, thinking: true },
        },
        'gemini-2.5-pro': {
          type: 'text' as const,
          capabilities: { vision: true, tools: true, thinking: true },
        },
      },
    },
  },
  {
    value: 'OpenRouter',
    label: 'OpenRouter',
    data: {
      protocol: 'openai-compatible' as LLMProtocol,
      apiUrl: 'https://openrouter.ai/api/v1/',
      models: {
        'openai/gpt-4o': {
          type: 'text' as const,
          capabilities: { vision: true, tools: true, thinking: false },
        },
        'deepseek/deepseek-chat-v3-0324': {
          type: 'text' as const,
          capabilities: { vision: false, tools: true, thinking: false },
        },
      },
    },
  },
  {
    value: 'deepseek',
    label: '深度求索 (DeepSeek)',
    data: {
      protocol: 'openai-compatible' as LLMProtocol,
      apiUrl: 'https://api.deepseek.com/v1/',
      models: {
        'deepseek-chat': {
          type: 'text' as const,
          capabilities: { vision: false, tools: true, thinking: false },
        },
      },
    },
  },
  {
    value: 'volces',
    label: '火山引擎 (Volces)',
    data: {
      protocol: 'openai-compatible' as LLMProtocol,
      apiUrl: 'https://ark.cn-beijing.volces.com/api/v3/',
      models: {
        'doubao-seed-1-6-250615': {
          type: 'text' as const,
          capabilities: { vision: true, tools: true, thinking: true },
        },
      },
    },
  },
  {
    value: 'siliconflow',
    label: '硅基流动 (SiliconFlow)',
    data: {
      protocol: 'openai-compatible' as LLMProtocol,
      apiUrl: 'https://api.siliconflow.cn/v1/',
      models: {},
    },
  },
  {
    value: 'zhipu',
    label: '智谱 AI (GLM)',
    data: {
      protocol: 'openai-compatible' as LLMProtocol,
      apiUrl: 'https://open.bigmodel.cn/api/paas/v4/',
      models: {},
    },
  },
  {
    value: 'moonshot',
    label: '月之暗面 (Kimi)',
    data: {
      protocol: 'openai-compatible' as LLMProtocol,
      apiUrl: 'https://api.moonshot.cn/v1/',
      models: {},
    },
  },
]

export default function AddProviderDialog({
  open,
  onOpenChange,
  onSave,
}: AddProviderDialogProps) {
  const { t } = useTranslation()
  const [providerName, setProviderName] = useState('')
  const [protocol, setProtocol] = useState<LLMProtocol>('openai-compatible')
  const [apiUrl, setApiUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [models, setModels] = useState<Record<string, ModelConfigEntry>>({})

  const handleProviderDataChange = (data: any) => {
    if (data && typeof data === 'object' && 'apiUrl' in data) {
      setApiUrl((data as { apiUrl: string }).apiUrl)
      if (data.protocol) {
        setProtocol(data.protocol as LLMProtocol)
      }
      setModels(data.models ?? {})
    }
  }

  const handleProtocolChange = (nextProtocol: LLMProtocol) => {
    setProtocol(nextProtocol)
    if (!apiUrl.trim()) {
      setApiUrl(DEFAULT_PROTOCOL_URLS[nextProtocol] || '')
    }
  }

  const resetForm = () => {
    setProviderName('')
    setProtocol('openai-compatible')
    setApiUrl('')
    setApiKey('')
    setModels({})
  }

  const handleSave = () => {
    if (!providerName.trim() || !apiUrl.trim()) {
      return
    }
    if (Object.keys(models).length === 0) {
      toast.error(t('settings:provider.noModelsSelected'))
      return
    }

    const config: LLMConfig = {
      models,
      url: apiUrl.trim(),
      api_key: apiKey,
      protocol,
      max_tokens: 8192,
      is_custom: true,
    }

    const providerKey = providerName.toLowerCase().replace(/\s+/g, '_')
    onSave(providerKey, config)
    resetForm()
    onOpenChange(false)
  }

  const handleCancel = () => {
    resetForm()
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <CommonDialogContent open={open}>
        <DialogHeader>
          <DialogTitle>{t('settings:provider.addProvider')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="provider-name">
              {t('settings:provider.providerName')}
            </Label>
            <Combobox
              id="provider-name"
              value={providerName}
              onChange={setProviderName}
              onDataChange={handleProviderDataChange}
              options={PROVIDER_OPTIONS}
              placeholder={t('settings:provider.providerNamePlaceholder')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="provider-protocol">接入协议</Label>
            <Select
              value={protocol}
              onValueChange={(val) => handleProtocolChange(val as LLMProtocol)}
            >
              <SelectTrigger id="provider-protocol">
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

          <div className="space-y-2">
            <Label htmlFor="api-url">{t('settings:provider.apiUrl')}</Label>
            <Input
              id="api-url"
              placeholder={t('settings:provider.apiUrlPlaceholder')}
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="api-key">{t('settings:provider.apiKey')}</Label>
            <Input
              id="api-key"
              type="password"
              placeholder={t('settings:provider.apiKeyPlaceholder')}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>

          <AddModelsList
            models={models}
            onChange={setModels}
            label={t('settings:models.title')}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel}>
            {t('settings:provider.cancel')}
          </Button>
          <Button
            onClick={handleSave}
            disabled={!providerName.trim() || !apiUrl.trim()}
          >
            {t('settings:provider.save')}
          </Button>
        </DialogFooter>
      </CommonDialogContent>
    </Dialog>
  )
}
