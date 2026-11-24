/** 程序说明：管理提供商下的文本模型列表及每项模型的 Vision / Tools / Thinking 能力标签。 */
import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ModelCapabilities } from '@/lib/llmProtocol'
import { Plus, Trash2 } from 'lucide-react'
import { Dialog, DialogContent, DialogTrigger } from '../ui/dialog'

export type ModelConfigEntry = {
  type?: 'text' | 'image' | 'video'
  is_custom?: boolean
  is_disabled?: boolean
  capabilities?: ModelCapabilities
}

export type ModelItem = {
  name: string
  type: 'text' | 'image' | 'video'
  capabilities: ModelCapabilities
  rawConfig?: ModelConfigEntry
}

interface ModelsListProps {
  models: Record<string, ModelConfigEntry>
  onChange: (models: Record<string, ModelConfigEntry>) => void
  label?: string
}

export default function AddModelsList({
  models,
  onChange,
  label = 'Models',
}: ModelsListProps) {
  const [modelItems, setModelItems] = useState<ModelItem[]>([])
  const [newModelName, setNewModelName] = useState('')
  const [newModelCaps, setNewModelCaps] = useState<ModelCapabilities>({
    vision: true,
    tools: true,
    thinking: false,
  })
  const [openAddModelDialog, setOpenAddModelDialog] = useState(false)

  useEffect(() => {
    const items = Object.entries(models).map(([name, config]) => ({
      name,
      type: (config?.type || 'text') as 'text' | 'image' | 'video',
      capabilities: {
        vision: Boolean(config?.capabilities?.vision),
        tools: config?.capabilities?.tools === undefined ? true : Boolean(config.capabilities.tools),
        thinking: Boolean(config?.capabilities?.thinking),
        ...(config?.capabilities?.context_length
          ? { context_length: config.capabilities.context_length }
          : {}),
      },
      rawConfig: config,
    }))
    setModelItems(items)
  }, [models])

  const notifyChange = useCallback(
    (items: ModelItem[]) => {
      const validModels = items.filter((model) => model.name.trim())
      const modelsConfig: Record<string, ModelConfigEntry> = {}

      validModels.forEach((model) => {
        modelsConfig[model.name] = {
          ...(model.rawConfig || {}),
          type: model.type,
          capabilities: model.capabilities,
        }
      })

      onChange(modelsConfig)
    },
    [onChange]
  )

  const handleAddModel = () => {
    if (newModelName.trim()) {
      const newItems: ModelItem[] = [
        ...modelItems,
        {
          name: newModelName.trim(),
          type: 'text',
          capabilities: { ...newModelCaps },
        },
      ]
      setModelItems(newItems)
      notifyChange(newItems)
      setNewModelName('')
      setNewModelCaps({ vision: true, tools: true, thinking: false })
      setOpenAddModelDialog(false)
    }
  }

  const handleToggleCapability = (
    index: number,
    capKey: 'vision' | 'tools' | 'thinking'
  ) => {
    const nextItems = modelItems.map((item, i) => {
      if (i !== index) return item
      return {
        ...item,
        capabilities: {
          ...item.capabilities,
          [capKey]: !item.capabilities?.[capKey],
        },
      }
    })
    setModelItems(nextItems)
    notifyChange(nextItems)
  }

  const handleRemoveModel = (index: number) => {
    if (modelItems.length > 1) {
      const newItems = modelItems.filter((_, i) => i !== index)
      setModelItems(newItems)
      notifyChange(newItems)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        <Dialog open={openAddModelDialog} onOpenChange={setOpenAddModelDialog}>
          <DialogTrigger asChild>
            <Button variant="secondary" size="sm">
              <Plus className="h-4 w-4 mr-1" />
              Add Model
            </Button>
          </DialogTrigger>
          <DialogContent>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Model Name</Label>
                <Input
                  type="text"
                  placeholder="gpt-4o / claude-sonnet-4-20250514 / gemini-2.5-flash"
                  value={newModelName}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      handleAddModel()
                    }
                  }}
                  onChange={(e) => setNewModelName(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-4 text-xs">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <Checkbox
                    checked={Boolean(newModelCaps.vision)}
                    onCheckedChange={(v) =>
                      setNewModelCaps((p) => ({ ...p, vision: Boolean(v) }))
                    }
                  />
                  Vision
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <Checkbox
                    checked={Boolean(newModelCaps.tools)}
                    onCheckedChange={(v) =>
                      setNewModelCaps((p) => ({ ...p, tools: Boolean(v) }))
                    }
                  />
                  Tools
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <Checkbox
                    checked={Boolean(newModelCaps.thinking)}
                    onCheckedChange={(v) =>
                      setNewModelCaps((p) => ({ ...p, thinking: Boolean(v) }))
                    }
                  />
                  Thinking
                </label>
              </div>
              <Button type="button" onClick={handleAddModel} className="w-full">
                Add Model
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="space-y-2">
        {modelItems.map((model, index) => (
          <div
            key={index}
            className="flex flex-wrap items-center justify-between gap-2 py-1 border-b border-border/50 last:border-b-0"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-mono truncate">{model.name}</p>
            </div>
            <div className="flex items-center gap-2">
              {(['vision', 'tools', 'thinking'] as const).map((cap) => {
                const active = Boolean(model.capabilities?.[cap])
                return (
                  <button
                    key={cap}
                    type="button"
                    onClick={() => handleToggleCapability(index, cap)}
                    className={`px-2 py-0.5 text-xs rounded border cursor-pointer transition-colors ${
                      active
                        ? 'bg-primary text-primary-foreground border-primary'
                        : 'bg-background text-muted-foreground border-border hover:bg-muted'
                    }`}
                  >
                    {cap}
                  </button>
                )
              })}
              <span className="text-xs text-muted-foreground px-1">
                {model.type}
              </span>
              {modelItems.length > 1 && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => handleRemoveModel(index)}
                  className="h-8 w-8 p-0"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
