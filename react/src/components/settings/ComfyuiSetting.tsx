/** 程序说明：ComfyUI 设置主面板，管理本地/线上多实例连接、鉴权、健康检查及工作流列表。 */
import UninstallProgressDialog from '@/components/comfyui/UninstallProgressDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
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
import { Switch } from '@/components/ui/switch'
import { PROVIDER_NAME_MAPPING } from '@/constants'
import { useRefreshModels } from '@/contexts/configs'
import { LLMConfig } from '@/types/types'
import {
  Activity,
  AlertCircle,
  CheckCircle,
  Pencil,
  Play,
  Plus,
  Server,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import ComfuiWorkflowSetting from './ComfyuiWorkflowSetting'

interface ComfyuiSettingProps {
  config: LLMConfig
  onConfigChange: (key: string, newConfig: LLMConfig) => void
}

type InstanceHealth = {
  online?: boolean
  latency_ms?: number
  error?: string
  devices?: { name?: string; vram_total?: number; vram_free?: number }[]
}

export type ComfyInstanceRecord = {
  id: string
  name: string
  base_url: string
  auth_type: 'none' | 'bearer' | 'basic' | 'header'
  auth_header_name: string
  auth_secret: string
  has_secret?: boolean
  max_concurrency: number
  timeout_sec: number
  enabled: number | boolean
  priority: number
  last_health_json?: string
}

const EMPTY_INSTANCE_FORM: ComfyInstanceRecord = {
  id: '',
  name: '',
  base_url: 'http://127.0.0.1:8188',
  auth_type: 'none',
  auth_header_name: 'X-API-Key',
  auth_secret: '',
  max_concurrency: 1,
  timeout_sec: 600,
  enabled: true,
  priority: 100,
}

function parseHealth(raw?: string): InstanceHealth | null {
  if (!raw) return null
  try {
    const obj = JSON.parse(raw)
    return obj && typeof obj === 'object' ? obj : null
  } catch {
    return null
  }
}

export default function ComfyuiSetting({
  config,
  onConfigChange,
}: ComfyuiSettingProps) {
  const { t } = useTranslation()
  const refreshModels = useRefreshModels()
  const [instances, setInstances] = useState<ComfyInstanceRecord[]>([])
  const [loadingInstances, setLoadingInstances] = useState(false)
  const [probingId, setProbingId] = useState<string | null>(null)
  const [showInstanceDialog, setShowInstanceDialog] = useState(false)
  const [instanceForm, setInstanceForm] =
    useState<ComfyInstanceRecord>(EMPTY_INSTANCE_FORM)
  const [isComfyUIInstalled, setIsComfyUIInstalled] = useState<boolean>(false)
  const [showUninstallDialog, setShowUninstallDialog] = useState<boolean>(false)

  const provider = PROVIDER_NAME_MAPPING.comfyui

  const loadInstances = useCallback(async () => {
    setLoadingInstances(true)
    try {
      const resp = await fetch('/api/settings/comfyui/instances')
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setInstances(Array.isArray(data.instances) ? data.instances : [])
    } catch (err) {
      console.error('Failed to load ComfyUI instances:', err)
    } finally {
      setLoadingInstances(false)
    }
  }, [])

  useEffect(() => {
    loadInstances()
  }, [loadInstances])

  useEffect(() => {
    const checkInstallation = async () => {
      try {
        const installed = await window.electronAPI?.checkComfyUIInstalled()
        setIsComfyUIInstalled(!!installed)
      } catch {
        setIsComfyUIInstalled(false)
      }
    }
    checkInstallation()
  }, [])

  const syncPrimaryUrlToParent = (nextList: ComfyInstanceRecord[]) => {
    const enabledFirst = nextList.find((item) => Boolean(item.enabled))
    onConfigChange('comfyui', {
      ...config,
      url: enabledFirst?.base_url || '',
    })
  }

  const handleProbeHealth = async (instanceId: string) => {
    setProbingId(instanceId)
    try {
      const resp = await fetch(
        `/api/settings/comfyui/instances/${encodeURIComponent(instanceId)}/health`,
        { method: 'POST' }
      )
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)
      await loadInstances()
      if (data.health?.online) {
        toast.success(
          `实例 ${instanceId} 在线（延迟 ${data.health.latency_ms} ms）`
        )
      } else {
        toast.warning(`实例 ${instanceId} 未连接: ${data.health?.error || '不可达'}`)
      }
    } catch (err) {
      toast.error(
        `健康检查失败: ${err instanceof Error ? err.message : String(err)}`
      )
    } finally {
      setProbingId(null)
    }
  }

  const handleSaveInstance = async () => {
    if (!instanceForm.name.trim() || !instanceForm.base_url.trim()) {
      toast.error('请填写实例名称与服务地址')
      return
    }
    try {
      const resp = await fetch('/api/settings/comfyui/instances', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: instanceForm.id || undefined,
          name: instanceForm.name.trim(),
          base_url: instanceForm.base_url.trim(),
          auth_type: instanceForm.auth_type,
          auth_header_name: instanceForm.auth_header_name,
          auth_secret: instanceForm.auth_secret,
          max_concurrency: Number(instanceForm.max_concurrency) || 1,
          timeout_sec: Number(instanceForm.timeout_sec) || 600,
          enabled: Boolean(instanceForm.enabled),
          priority: Number(instanceForm.priority) || 100,
        }),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`)

      setShowInstanceDialog(false)
      const updatedListResp = await fetch('/api/settings/comfyui/instances')
      const updatedData = await updatedListResp.json()
      const nextList = Array.isArray(updatedData.instances)
        ? updatedData.instances
        : []
      setInstances(nextList)
      syncPrimaryUrlToParent(nextList)
      refreshModels()
      toast.success('ComfyUI 实例已保存')
    } catch (err) {
      toast.error(
        `保存实例失败: ${err instanceof Error ? err.message : String(err)}`
      )
    }
  }

  const handleDeleteInstance = async (instanceId: string) => {
    try {
      const resp = await fetch(
        `/api/settings/comfyui/instances/${encodeURIComponent(instanceId)}`,
        { method: 'DELETE' }
      )
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const next = instances.filter((i) => i.id !== instanceId)
      setInstances(next)
      syncPrimaryUrlToParent(next)
      refreshModels()
      toast.success('实例已删除')
    } catch (err) {
      toast.error(
        `删除实例失败: ${err instanceof Error ? err.message : String(err)}`
      )
    }
  }

  const handleToggleInstance = async (
    inst: ComfyInstanceRecord,
    enabled: boolean
  ) => {
    try {
      const resp = await fetch(
        `/api/settings/comfyui/instances/${encodeURIComponent(inst.id)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: inst.id,
            name: inst.name,
            base_url: inst.base_url,
            auth_type: inst.auth_type,
            auth_header_name: inst.auth_header_name,
            auth_secret: inst.auth_secret,
            max_concurrency: inst.max_concurrency,
            timeout_sec: inst.timeout_sec,
            enabled,
            priority: inst.priority,
          }),
        }
      )
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await loadInstances()
      refreshModels()
    } catch (err) {
      toast.error(
        `切换实例状态失败: ${err instanceof Error ? err.message : String(err)}`
      )
    }
  }

  const handleConfirmUninstall = async () => {
    try {
      await window.electronAPI?.stopComfyUIProcess()
    } catch {
      // 忽略停止异常继续卸载流程
    }
    try {
      await window.electronAPI?.uninstallComfyUI()
    } catch (error) {
      console.error('Error starting uninstallation:', error)
    }
  }

  return (
    <div className="space-y-6">
      {/* Provider Header */}
      <div className="flex flex-wrap items-center gap-2">
        <img
          src={provider.icon}
          alt={provider.name}
          className="w-10 h-10 rounded-full"
        />
        <p className="font-bold text-2xl w-fit">{provider.name}</p>
        <span className="text-sm text-muted-foreground">
          {t('settings:comfyui.localImageGeneration')}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {isComfyUIInstalled && (
            <>
              <Button
                onClick={() => window.electronAPI?.startComfyUIProcess()}
                variant="outline"
                size="sm"
                className="border-green-300 text-green-700 hover:bg-green-50"
              >
                <Play className="w-4 h-4 mr-1.5" />
                {t('settings:comfyui.startButton')}
              </Button>
              <Button
                onClick={() => setShowUninstallDialog(true)}
                variant="outline"
                size="sm"
                className="border-red-300 text-red-700 hover:bg-red-50"
                disabled={showUninstallDialog}
              >
                <Trash2 className="w-4 h-4 mr-1.5" />
                {t('settings:comfyui.uninstallButton')}
              </Button>
            </>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setInstanceForm({ ...EMPTY_INSTANCE_FORM })
              setShowInstanceDialog(true)
            }}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            新增 ComfyUI 实例
          </Button>
        </div>
      </div>

      {/* 多实例管理列表 */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Server className="w-4 h-4" />
          <span>ComfyUI 计算节点（支持本地 / 反向代理 / 远程鉴权多实例）</span>
        </div>

        {loadingInstances && instances.length === 0 ? (
          <div className="text-xs text-muted-foreground py-2">加载实例中...</div>
        ) : instances.length === 0 ? (
          <div className="border rounded-lg p-4 text-sm text-muted-foreground">
            尚未配置 ComfyUI 实例，请点击右上角「新增 ComfyUI 实例」。
          </div>
        ) : (
          <div className="space-y-2">
            {instances.map((inst) => {
              const health = parseHealth(inst.last_health_json)
              const enabled = Boolean(inst.enabled)
              return (
                <Card key={inst.id} className={!enabled ? 'opacity-65' : ''}>
                  <CardContent className="py-3 px-4 flex flex-wrap items-center justify-between gap-3">
                    <div className="space-y-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-sm">{inst.name}</span>
                        <code className="text-xs px-1.5 py-0.5 rounded bg-muted">
                          {inst.id}
                        </code>
                        <Badge variant="outline">鉴权: {inst.auth_type}</Badge>
                        <Badge variant="outline">并发: {inst.max_concurrency}</Badge>
                        {health?.online === true && (
                          <Badge variant="secondary" className="text-green-700 bg-green-100">
                            <CheckCircle className="w-3 h-3 mr-1" />
                            在线 ({health.latency_ms}ms)
                          </Badge>
                        )}
                        {health?.online === false && (
                          <Badge variant="destructive">
                            <AlertCircle className="w-3 h-3 mr-1" />
                            离线
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground font-mono truncate">
                        {inst.base_url}
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <Switch
                        checked={enabled}
                        onCheckedChange={(checked) => handleToggleInstance(inst, checked)}
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={probingId === inst.id}
                        onClick={() => handleProbeHealth(inst.id)}
                      >
                        <Activity
                          className={`w-4 h-4 mr-1 ${
                            probingId === inst.id ? 'animate-pulse' : ''
                          }`}
                        />
                        检测
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setInstanceForm({
                            ...inst,
                            enabled: Boolean(inst.enabled),
                          })
                          setShowInstanceDialog(true)
                        }}
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>
                      {instances.length > 1 && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-red-600 hover:bg-red-50"
                          onClick={() => handleDeleteInstance(inst.id)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>

      {/* 工作流管理与开关 */}
      <ComfuiWorkflowSetting instances={instances} />

      {/* 实例编辑弹窗 */}
      <Dialog open={showInstanceDialog} onOpenChange={setShowInstanceDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {instanceForm.id ? `编辑实例：${instanceForm.id}` : '新增 ComfyUI 实例'}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>实例 ID（英文唯一标识）</Label>
                <Input
                  placeholder="留空则按名称生成"
                  value={instanceForm.id}
                  onChange={(e) =>
                    setInstanceForm((p) => ({ ...p, id: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>显示名称</Label>
                <Input
                  placeholder="例如 本地 4090 / 云端 A100"
                  value={instanceForm.name}
                  onChange={(e) =>
                    setInstanceForm((p) => ({ ...p, name: e.target.value }))
                  }
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>服务基础 URL（支持反代路径前缀，如 https://gpu.example.com/comfy）</Label>
              <Input
                placeholder="http://127.0.0.1:8188"
                value={instanceForm.base_url}
                onChange={(e) =>
                  setInstanceForm((p) => ({ ...p, base_url: e.target.value }))
                }
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>鉴权方式</Label>
                <Select
                  value={instanceForm.auth_type}
                  onValueChange={(val) =>
                    setInstanceForm((p) => ({
                      ...p,
                      auth_type: val as ComfyInstanceRecord['auth_type'],
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">无鉴权</SelectItem>
                    <SelectItem value="bearer">Bearer Token</SelectItem>
                    <SelectItem value="basic">Basic (user:pass)</SelectItem>
                    <SelectItem value="header">自定义 Header</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {instanceForm.auth_type === 'header' && (
                <div className="space-y-1.5">
                  <Label>Header 名称</Label>
                  <Input
                    value={instanceForm.auth_header_name}
                    onChange={(e) =>
                      setInstanceForm((p) => ({
                        ...p,
                        auth_header_name: e.target.value,
                      }))
                    }
                  />
                </div>
              )}
            </div>

            {instanceForm.auth_type !== 'none' && (
              <div className="space-y-1.5">
                <Label>鉴权密钥（保留掩码则不覆盖原密钥）</Label>
                <Input
                  type="password"
                  value={instanceForm.auth_secret}
                  onChange={(e) =>
                    setInstanceForm((p) => ({ ...p, auth_secret: e.target.value }))
                  }
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>最大并发数</Label>
                <Input
                  type="number"
                  min={1}
                  value={instanceForm.max_concurrency}
                  onChange={(e) =>
                    setInstanceForm((p) => ({
                      ...p,
                      max_concurrency: parseInt(e.target.value, 10) || 1,
                    }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>优先级（越小越优先）</Label>
                <Input
                  type="number"
                  value={instanceForm.priority}
                  onChange={(e) =>
                    setInstanceForm((p) => ({
                      ...p,
                      priority: parseInt(e.target.value, 10) || 100,
                    }))
                  }
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowInstanceDialog(false)}
            >
              取消
            </Button>
            <Button onClick={handleSaveInstance}>保存实例</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <UninstallProgressDialog
        open={showUninstallDialog}
        onOpenChange={setShowUninstallDialog}
        onUninstallComplete={() => setIsComfyUIInstalled(false)}
        onConfirmUninstall={handleConfirmUninstall}
      />
    </div>
  )
}
