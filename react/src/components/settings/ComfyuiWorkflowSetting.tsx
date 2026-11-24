/** 程序说明：ComfyUI 工作流管理组件，支持 AI Agent 一键解析导入、workflows/ 成对文件自动同步、启用关闭 Switch 与原地更新/导出。 */
import { useEffect, useRef, useState } from 'react'
import { useConfigs, useRefreshModels } from '@/contexts/configs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Textarea } from '@/components/ui/textarea'
import {
  classifyWorkflowFiles,
  downloadJsonFile,
  formatCapabilityLabel,
  suggestWorkflowName,
} from '@/lib/comfyWorkflowPack'
import {
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronUp,
  Download,
  FileJson,
  FolderSync,
  Pencil,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'

export type ComfyInstanceOption = {
  id: string
  name: string
  base_url: string
  enabled?: number | boolean
}

export type ComfyWorkflowInputParam = {
  name: string
  type: string
  description: string
  node_id: string
  node_input_name: string
  default_value: unknown
  required: boolean
  options?: unknown[]
}

export type ComfyWorkflowRecord = {
  id: number
  name: string
  display_name: string
  description: string
  capability: string
  output_kind: 'image' | 'video' | 'audio' | string
  instance_id: string
  source_mode: 'db' | 'pack_dir' | 'pack_pair' | string
  source_path: string
  seed_strategy: 'random' | 'fixed' | 'param' | string
  schema_version: number
  enabled: boolean
  checksum: string
  inputs: ComfyWorkflowInputParam[]
  api_json: Record<string, unknown>
  outputs?: unknown
  validation_errors: string[]
}

interface ComfyuiWorkflowSettingProps {
  instances?: ComfyInstanceOption[]
}

const CAPABILITY_OPTIONS = [
  { value: 't2i', label: '文生图 (t2i)' },
  { value: 'i2i', label: '图生图/编辑 (i2i)' },
  { value: 'inpaint', label: '局部重绘 (inpaint)' },
  { value: 'upscale', label: '超分放大 (upscale)' },
  { value: 't2v', label: '文生视频 (t2v)' },
  { value: 'i2v', label: '图生视频 (i2v)' },
  { value: 'tts', label: '语音合成 (tts)' },
  { value: 'music', label: '音乐生成 (music)' },
  { value: 'custom', label: '自定义 (custom)' },
]

export default function ComfuiWorkflowSetting({
  instances = [],
}: ComfyuiWorkflowSettingProps) {
  const { textModels, textModel } = useConfigs()
  const refreshModels = useRefreshModels()
  const [workflows, setWorkflows] = useState<ComfyWorkflowRecord[]>([])
  const [workflowsDir, setWorkflowsDir] = useState<string>('workflows/')
  const [pendingSourceFiles, setPendingSourceFiles] = useState<
    Array<{ filename: string; path: string }>
  >([])
  const [syncingSource, setSyncingSource] = useState(false)
  const [autoImportSource, setAutoImportSource] = useState(false)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [togglingId, setTogglingId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<ComfyWorkflowRecord | null>(null)
  const [editTarget, setEditTarget] = useState<ComfyWorkflowRecord | null>(null)
  const [editForm, setEditForm] = useState({
    display_name: '',
    description: '',
    capability: 't2i',
    output_kind: 'image',
    instance_id: '',
    seed_strategy: 'random',
    enabled: true,
    inputsText: '[]',
  })

  // 导入弹窗状态
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importTab, setImportTab] = useState<'ai' | 'pair' | 'draft'>('ai')
  const [apiText, setApiText] = useState('')
  const [configText, setConfigText] = useState('')
  const [draftName, setDraftName] = useState('custom_workflow')
  const [aiUserHint, setAiUserHint] = useState('')
  const [aiModelKey, setAiModelKey] = useState<string>('auto')
  const [aiRunning, setAiRunning] = useState(false)
  const [aiStatusInfo, setAiStatusInfo] = useState<{
    model_used: string
    repaired: boolean
    used_object_info: boolean
  } | null>(null)
  const [saveToDir, setSaveToDir] = useState(true)
  const [importError, setImportError] = useState('')
  const [submittingImport, setSubmittingImport] = useState(false)

  const aiApiInputRef = useRef<HTMLInputElement>(null)
  const pairFileInputRef = useRef<HTMLInputElement>(null)
  const draftApiInputRef = useRef<HTMLInputElement>(null)

  const loadWorkflows = async () => {
    setLoading(true)
    try {
      const resp = await fetch('/api/settings/comfyui/workflows')
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      const data = await resp.json()
      setWorkflowsDir(data.workflows_dir || 'workflows/')
      setWorkflows(Array.isArray(data.workflows) ? data.workflows : [])
      setPendingSourceFiles(
        Array.isArray(data.pending_source_files) ? data.pending_source_files : []
      )
    } catch (err) {
      toast.error(
        `加载工作流列表失败: ${err instanceof Error ? err.message : String(err)}`
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadWorkflows()
    // 读取 workflows/source/ 自动导入开关（默认关闭）
    fetch('/api/settings/comfyui/workflows/source_settings')
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => {
        if (data && typeof data.auto_import_source === 'boolean') {
          setAutoImportSource(data.auto_import_source)
        }
      })
      .catch(() => undefined)
  }, [])

  const handleToggleAutoImportSource = async (next: boolean) => {
    setAutoImportSource(next)
    try {
      const resp = await fetch('/api/settings/comfyui/workflows/source_settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_import_source: next }),
      })
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      toast.success(next ? '已开启启动时自动导入 workflows/source/' : '已关闭自动导入')
    } catch (err) {
      setAutoImportSource(!next)
      toast.error(`保存失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const handleToggleEnabled = async (wf: ComfyWorkflowRecord, nextEnabled: boolean) => {
    setTogglingId(wf.id)
    try {
      const resp = await fetch(`/api/settings/comfyui/workflows/${wf.id}/enabled`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: nextEnabled }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      setWorkflows((prev) =>
        prev.map((item) => (item.id === wf.id ? { ...item, enabled: nextEnabled } : item))
      )
      refreshModels()
      toast.success(
        nextEnabled
          ? `已启用「${wf.display_name || wf.name}」，Agent 现在可以选用`
          : `已停用「${wf.display_name || wf.name}」，Agent 将不再选用`
      )
    } catch (err) {
      toast.error(
        `切换状态失败: ${err instanceof Error ? err.message : String(err)}`
      )
    } finally {
      setTogglingId(null)
    }
  }

  const handleScanDir = async () => {
    setScanning(true)
    try {
      const resp = await fetch('/api/settings/comfyui/workflows/scan', {
        method: 'POST',
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      await loadWorkflows()
      refreshModels()
      const syncedCount = Array.isArray(data.synced) ? data.synced.length : 0
      const errCount = Array.isArray(data.errors) ? data.errors.length : 0
      if (errCount > 0) {
        toast.warning(
          `同步 ${syncedCount} 个工作流，另有 ${errCount} 个文件校验未通过（请检查格式）`
        )
      } else {
        toast.success(`扫描完成：已同步 ${syncedCount} 个项目目录工作流`)
      }
    } catch (err) {
      toast.error(
        `扫描工作流目录失败: ${err instanceof Error ? err.message : String(err)}`
      )
    } finally {
      setScanning(false)
    }
  }

  const handleSyncSourceFiles = async () => {
    setSyncingSource(true)
    try {
      const resp = await fetch('/api/settings/comfyui/workflows/sync_source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fallback_to_draft: false }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      await loadWorkflows()
      refreshModels()
      const importedCount = Array.isArray(data.imported) ? data.imported.length : 0
      const skippedCount = Array.isArray(data.skipped_no_llm)
        ? data.skipped_no_llm.length
        : 0
      const errCount = Array.isArray(data.errors) ? data.errors.length : 0
      if (importedCount > 0) {
        toast.success(`已从 workflows/source/ 自动导入 ${importedCount} 个新工作流`)
      } else if (skippedCount > 0) {
        toast.warning(
          `检测到 ${skippedCount} 个待导入工作流，请先配置可用文本大模型，或由外部 AI Agent 执行 workflow_cli.py 导入`
        )
      } else if (errCount > 0) {
        toast.error(`自动导入存在 ${errCount} 个失败项`)
      } else {
        toast.info('workflows/source/ 中没有需要导入的新文件')
      }
    } catch (err) {
      toast.error(
        `自动导入 workflows/source/ 失败: ${err instanceof Error ? err.message : String(err)}`
      )
    } finally {
      setSyncingSource(false)
    }
  }

  const handleExportToDir = async (wf: ComfyWorkflowRecord) => {
    try {
      const resp = await fetch(`/api/settings/comfyui/workflows/${wf.id}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ save_to_dir: true }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      await loadWorkflows()
      toast.success(`已导出到项目目录：workflows/${data.saved_path}/`)
    } catch (err) {
      toast.error(`导出失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const handleDownloadPair = async (wf: ComfyWorkflowRecord) => {
    try {
      const resp = await fetch(`/api/settings/comfyui/workflows/${wf.id}/export`)
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      downloadJsonFile(`${wf.name}.api.json`, data.api_json)
      downloadJsonFile(`${wf.name}.jaaz.json`, data.config_json)
      toast.success(`已导出 ${wf.name}.api.json 与 ${wf.name}.jaaz.json`)
    } catch (err) {
      toast.error(`下载失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const handleDeleteWorkflow = async () => {
    if (!deleteTarget) return
    try {
      const resp = await fetch(`/api/settings/comfyui/workflows/${deleteTarget.id}`, {
        method: 'DELETE',
      })
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      setDeleteTarget(null)
      await loadWorkflows()
      refreshModels()
      toast.success('工作流已删除')
    } catch (err) {
      toast.error(`删除失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const openEditDialog = (wf: ComfyWorkflowRecord) => {
    setEditTarget(wf)
    setEditForm({
      display_name: wf.display_name || wf.name,
      description: wf.description || '',
      capability: wf.capability || 't2i',
      output_kind: wf.output_kind || 'image',
      instance_id: wf.instance_id || '',
      seed_strategy: wf.seed_strategy || 'random',
      enabled: wf.enabled,
      inputsText: JSON.stringify(wf.inputs || [], null, 2),
    })
  }

  const handleSaveEdit = async () => {
    if (!editTarget) return
    let parsedInputs: unknown
    try {
      parsedInputs = JSON.parse(editForm.inputsText)
    } catch (err) {
      toast.error(
        `参数 JSON 格式无效: ${err instanceof Error ? err.message : String(err)}`
      )
      return
    }

    try {
      const resp = await fetch(`/api/settings/comfyui/workflows/${editTarget.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          display_name: editForm.display_name,
          description: editForm.description,
          capability: editForm.capability,
          output_kind: editForm.output_kind,
          instance_id: editForm.instance_id || '',
          seed_strategy: editForm.seed_strategy,
          enabled: editForm.enabled,
          inputs: parsedInputs,
        }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      setEditTarget(null)
      await loadWorkflows()
      refreshModels()
      toast.success('工作流已更新（原地事务更新，无数据丢失风险）')
    } catch (err) {
      toast.error(`保存失败: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  const openImportModal = (tab: 'ai' | 'pair' | 'draft') => {
    setImportTab(tab)
    setApiText('')
    setConfigText('')
    setDraftName('')
    setAiUserHint('')
    setAiStatusInfo(null)
    setAiModelKey(
      textModel ? `${textModel.provider}:${textModel.model}` : 'auto'
    )
    setImportError('')
    setShowImportDialog(true)
  }

  const handlePickAiApiFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const text = await file.text()
    const classified = classifyWorkflowFiles([{ name: file.name, content: text }])
    if (classified.errors.length > 0 || !classified.apiJson) {
      setImportError(classified.errors.join('\n') || '请上传有效的 ComfyUI API JSON')
      return
    }
    setImportError('')
    setApiText(JSON.stringify(classified.apiJson, null, 2))
    if (!draftName.trim()) {
      setDraftName(suggestWorkflowName(file.name))
    }
  }

  const handleAiImport = async (autoSave: boolean) => {
    setImportError('')
    if (!apiText.trim()) {
      setImportError('请先选择或粘贴 ComfyUI Export (API) JSON')
      return
    }
    let parsedApi: unknown
    try {
      parsedApi = JSON.parse(apiText)
    } catch (err) {
      setImportError(
        `API JSON 语法有误: ${err instanceof Error ? err.message : String(err)}`
      )
      return
    }

    let provider = ''
    let model = ''
    if (aiModelKey && aiModelKey !== 'auto') {
      const sep = aiModelKey.indexOf(':')
      if (sep > 0) {
        provider = aiModelKey.slice(0, sep)
        model = aiModelKey.slice(sep + 1)
      }
    }

    setAiRunning(true)
    try {
      const resp = await fetch('/api/settings/comfyui/workflows/ai_import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_json: parsedApi,
          name: draftName.trim(),
          user_hint: aiUserHint.trim(),
          provider,
          model,
          auto_save: autoSave,
          save_to_dir: saveToDir,
        }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      setConfigText(JSON.stringify(data.config_json, null, 2))
      setAiStatusInfo({
        model_used: data.model_used || '',
        repaired: Boolean(data.repaired),
        used_object_info: Boolean(data.used_object_info),
      })
      if (autoSave) {
        setShowImportDialog(false)
        await loadWorkflows()
        refreshModels()
        toast.success(
          `AI 已完成解析并导入工作流「${data.config_json?.display_name || data.config_json?.name}」`
        )
      } else {
        toast.success('AI 已生成并通过严格校验，可在下方微调或直接点击「校验并导入」')
      }
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err))
    } finally {
      setAiRunning(false)
    }
  }

  const handlePickPairFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = Array.from(e.target.files || [])
    e.target.value = ''
    if (fileList.length === 0) return

    const contents = await Promise.all(
      fileList.map(async (file) => ({
        name: file.name,
        content: await file.text(),
      }))
    )

    const classified = classifyWorkflowFiles(contents)
    if (classified.errors.length > 0) {
      setImportError(classified.errors.join('\n'))
      return
    }
    setImportError('')

    if (classified.apiJson) {
      setApiText(JSON.stringify(classified.apiJson, null, 2))
      setDraftName(classified.suggestedName)
    }
    if (classified.configJson) {
      setConfigText(JSON.stringify(classified.configJson, null, 2))
    } else if (classified.mode === 'single_api' && classified.apiJson) {
      // 用户只选了一个 API JSON 时自动协助生成草稿
      setImportTab('draft')
      await requestDraftConfig(classified.apiJson, classified.suggestedName)
    }
  }

  const requestDraftConfig = async (
    apiJsonObj: Record<string, unknown>,
    name: string
  ) => {
    try {
      const resp = await fetch('/api/settings/comfyui/workflows/draft_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_json: apiJsonObj, name }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      setConfigText(JSON.stringify(data.config_json, null, 2))
      setImportError('')
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err))
    }
  }

  const handlePickDraftApiFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const text = await file.text()
    const classified = classifyWorkflowFiles([{ name: file.name, content: text }])
    if (classified.errors.length > 0 || !classified.apiJson) {
      setImportError(classified.errors.join('\n') || '请上传有效的 ComfyUI API JSON')
      return
    }
    setApiText(JSON.stringify(classified.apiJson, null, 2))
    const suggested = suggestWorkflowName(file.name)
    setDraftName(suggested)
    await requestDraftConfig(classified.apiJson, suggested)
  }

  const handleSubmitImport = async () => {
    setImportError('')
    if (!apiText.trim() || !configText.trim()) {
      setImportError('请同时提供 ComfyUI API JSON 与 Jaaz 工作流配置文件')
      return
    }
    let parsedApi: unknown
    let parsedConfig: unknown
    try {
      parsedApi = JSON.parse(apiText)
    } catch (err) {
      setImportError(
        `API JSON 语法有误: ${err instanceof Error ? err.message : String(err)}`
      )
      return
    }
    try {
      parsedConfig = JSON.parse(configText)
    } catch (err) {
      setImportError(
        `Jaaz 配置文件语法有误: ${err instanceof Error ? err.message : String(err)}`
      )
      return
    }

    setSubmittingImport(true)
    try {
      const resp = await fetch('/api/settings/comfyui/workflows/import_pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_json: parsedApi,
          config_json: parsedConfig,
          save_to_dir: saveToDir,
        }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      setShowImportDialog(false)
      await loadWorkflows()
      refreshModels()
      toast.success('工作流已校验并导入生效')
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmittingImport(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-semibold text-base">ComfyUI 工作流与 Agent 开关</p>
          <p className="text-xs text-muted-foreground">
            项目固定目录：<code className="px-1 py-0.5 rounded bg-muted">{workflowsDir}</code>（支持外部 AI Agent 写入成对文件自动同步；仅“已启用”工作流可被对话 Agent 选用）
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleScanDir}
            disabled={scanning}
          >
            <FolderSync className={`w-4 h-4 mr-1.5 ${scanning ? 'animate-spin' : ''}`} />
            扫描 workflows/ 同步
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => openImportModal('pair')}
          >
            <Upload className="w-4 h-4 mr-1.5" />
            导入成对文件
          </Button>
          <Button size="sm" onClick={() => openImportModal('ai')}>
            <Bot className="w-4 h-4 mr-1.5" />
            AI 一键导入
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-xs">
        <div className="text-muted-foreground">
          启动时自动导入 <code className="px-1 py-0.5 rounded bg-muted">workflows/source/</code> 中的新文件（调用已配置文本模型，会消耗 token；默认关闭）
        </div>
        <Switch
          checked={autoImportSource}
          onCheckedChange={handleToggleAutoImportSource}
        />
      </div>

      {pendingSourceFiles.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-blue-500/30 bg-blue-500/5 px-3 py-2 text-xs">
          <div className="text-foreground">
            检测到 <code className="px-1 py-0.5 rounded bg-muted">workflows/source/</code> 中有{' '}
            <strong>{pendingSourceFiles.length}</strong> 个待导入的原始工作流（
            {pendingSourceFiles
              .slice(0, 3)
              .map((item) => item.filename)
              .join('、')}
            {pendingSourceFiles.length > 3 ? ' 等' : ''}）。
          </div>
          <Button
            size="sm"
            variant="secondary"
            onClick={handleSyncSourceFiles}
            disabled={syncingSource}
          >
            <Sparkles
              className={`w-3.5 h-3.5 mr-1 ${syncingSource ? 'animate-spin' : ''}`}
            />
            {syncingSource ? '导入中...' : 'AI 自动导入新文件'}
          </Button>
        </div>
      )}

      {loading ? (
        <div className="text-sm text-muted-foreground py-6 text-center">
          <RefreshCw className="w-4 h-4 inline animate-spin mr-2" />
          正在加载工作流...
        </div>
      ) : workflows.length === 0 ? (
        <div className="border rounded-lg p-6 text-center text-sm text-muted-foreground">
          暂无 ComfyUI 工作流。请点击右上角「导入成对文件」，或将{' '}
          <code>workflow.api.json</code> + <code>jaaz.workflow.json</code> 放入项目{' '}
          <code>workflows/</code> 目录后点击扫描同步。
        </div>
      ) : (
        <div className="space-y-3">
          {workflows.map((wf) => {
            const isExpanded = expandedId === wf.id
            const hasErrors = wf.validation_errors && wf.validation_errors.length > 0
            return (
              <Card
                key={wf.id}
                className={`transition-opacity ${!wf.enabled ? 'opacity-65 bg-muted/30' : ''}`}
              >
                <CardHeader className="py-3 px-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="space-y-1 min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-base">
                          {wf.display_name || wf.name}
                        </CardTitle>
                        <code className="text-xs px-1.5 py-0.5 rounded bg-muted">
                          {wf.name}
                        </code>
                        <Badge variant="secondary">
                          {formatCapabilityLabel(wf.capability)}
                        </Badge>
                        <Badge variant="outline">{wf.output_kind || 'image'}</Badge>
                        <Badge variant="outline">
                          {wf.source_mode === 'db'
                            ? '仅数据库'
                            : `workflows/${wf.source_path || wf.name}`}
                        </Badge>
                        {wf.instance_id && (
                          <Badge variant="outline">实例: {wf.instance_id}</Badge>
                        )}
                        {!wf.enabled && (
                          <Badge variant="destructive">已关闭（Agent 不可选）</Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground line-clamp-2">
                        {wf.description || '无描述'}
                      </p>
                      {hasErrors && (
                        <div className="flex items-start gap-1.5 text-xs text-red-600 mt-1">
                          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                          <span>{wf.validation_errors.join('；')}</span>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <div className="flex items-center gap-1.5 pr-2 border-r">
                        <span className="text-xs text-muted-foreground">
                          {wf.enabled ? '已启用' : '已关闭'}
                        </span>
                        <Switch
                          checked={wf.enabled}
                          disabled={togglingId === wf.id}
                          onCheckedChange={(checked) => handleToggleEnabled(wf, checked)}
                        />
                      </div>

                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setExpandedId(isExpanded ? null : wf.id)}
                        title="查看参数映射"
                      >
                        参数 ({wf.inputs?.length || 0})
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4 ml-1" />
                        ) : (
                          <ChevronDown className="w-4 h-4 ml-1" />
                        )}
                      </Button>

                      {wf.source_mode === 'db' && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExportToDir(wf)}
                          title="转换为标准文件对并保存到项目 workflows/ 目录"
                        >
                          <FileJson className="w-4 h-4 mr-1" />
                          转存目录
                        </Button>
                      )}

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDownloadPair(wf)}
                        title="下载成对 JSON 文件"
                      >
                        <Download className="w-4 h-4" />
                      </Button>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openEditDialog(wf)}
                        title="查看/编辑元数据"
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>

                      <Button
                        variant="outline"
                        size="sm"
                        className="text-red-600 hover:bg-red-50"
                        onClick={() => setDeleteTarget(wf)}
                        title="删除工作流"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>

                {isExpanded && (
                  <CardContent className="pt-0 pb-3 px-4">
                    <div className="rounded-md border overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-muted/50 text-left">
                          <tr>
                            <th className="p-2">参数名</th>
                            <th className="p-2">类型</th>
                            <th className="p-2">必填</th>
                            <th className="p-2">节点映射</th>
                            <th className="p-2">默认值</th>
                            <th className="p-2">说明</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(wf.inputs || []).map((param, i) => (
                            <tr key={i} className="border-t">
                              <td className="p-2 font-mono">{param.name}</td>
                              <td className="p-2">{param.type}</td>
                              <td className="p-2">{param.required ? '是' : '否'}</td>
                              <td className="p-2 font-mono">
                                {param.node_id}.{param.node_input_name}
                              </td>
                              <td className="p-2 font-mono max-w-[160px] truncate">
                                {param.default_value === undefined || param.default_value === null
                                  ? '-'
                                  : String(param.default_value)}
                              </td>
                              <td className="p-2 text-muted-foreground">
                                {param.description || '-'}
                              </td>
                            </tr>
                          ))}
                          {(!wf.inputs || wf.inputs.length === 0) && (
                            <tr>
                              <td colSpan={6} className="p-3 text-center text-muted-foreground">
                                未定义动态输入参数
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                )}
              </Card>
            )
          })}
        </div>
      )}

      {/* 导入/AI 解析弹窗 */}
      <Dialog open={showImportDialog} onOpenChange={setShowImportDialog}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>导入 ComfyUI 工作流（AI 自动解析 / 成对文件）</DialogTitle>
            <DialogDescription>
              只需上传 ComfyUI <code>Export (API)</code> 导出的 JSON，由 AI Agent 自动分析节点并生成{' '}
              <code>jaaz.workflow.json</code>；也可直接导入已准备好的成对文件至{' '}
              <code>workflows/</code> 目录。
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-wrap gap-2 p-1 bg-muted rounded-md w-fit">
            <Button
              type="button"
              size="sm"
              variant={importTab === 'ai' ? 'default' : 'ghost'}
              onClick={() => setImportTab('ai')}
            >
              <Bot className="w-4 h-4 mr-1" />
              AI 自动解析导入（推荐）
            </Button>
            <Button
              type="button"
              size="sm"
              variant={importTab === 'pair' ? 'default' : 'ghost'}
              onClick={() => setImportTab('pair')}
            >
              导入成对文件
            </Button>
            <Button
              type="button"
              size="sm"
              variant={importTab === 'draft' ? 'default' : 'ghost'}
              onClick={() => setImportTab('draft')}
            >
              离线规则模板
            </Button>
          </div>

          {importTab === 'ai' ? (
            <div className="space-y-3 p-3 border rounded-md bg-muted/20">
              <div className="flex flex-wrap items-center gap-3">
                <input
                  ref={aiApiInputRef}
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={handlePickAiApiFile}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => aiApiInputRef.current?.click()}
                >
                  <Upload className="w-4 h-4 mr-1.5" />
                  上传 ComfyUI API JSON
                </Button>
                <div className="flex items-center gap-2">
                  <Label className="text-xs whitespace-nowrap">解析模型:</Label>
                  <Select value={aiModelKey} onValueChange={setAiModelKey}>
                    <SelectTrigger className="h-8 w-56 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">自动选择已配置文本模型</SelectItem>
                      {(textModels || []).map((m) => {
                        const key = `${m.provider}:${m.model}`
                        return (
                          <SelectItem key={key} value={key}>
                            {m.provider} / {m.model}
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                </div>
                <Input
                  placeholder="可选工具英文名（留空由 AI 自动命名）"
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  className="h-8 w-56 text-xs"
                />
              </div>

              <Input
                placeholder="可选一句话说明（如：MOSS 文生图，只暴露提示词和画幅比例，不要暴露采样器）"
                value={aiUserHint}
                onChange={(e) => setAiUserHint(e.target.value)}
                className="text-xs"
              />

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={aiRunning}
                  onClick={() => handleAiImport(false)}
                >
                  <Sparkles className="w-4 h-4 mr-1" />
                  {aiRunning ? 'AI 解析中...' : 'AI 解析预览配置'}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={aiRunning}
                  onClick={() => handleAiImport(true)}
                >
                  <Bot className="w-4 h-4 mr-1" />
                  {aiRunning ? 'AI 解析导入中...' : 'AI 解析并直接导入'}
                </Button>
                {aiStatusInfo && (
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <Badge variant="outline">模型: {aiStatusInfo.model_used}</Badge>
                    {aiStatusInfo.used_object_info && (
                      <Badge variant="secondary">已读取 ComfyUI 节点枚举</Badge>
                    )}
                    {aiStatusInfo.repaired && (
                      <Badge variant="secondary">已自动自检纠错</Badge>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : importTab === 'pair' ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3 p-3 border rounded-md bg-muted/20">
                <input
                  ref={pairFileInputRef}
                  type="file"
                  accept=".json"
                  multiple
                  className="hidden"
                  onChange={handlePickPairFiles}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => pairFileInputRef.current?.click()}
                >
                  <Upload className="w-4 h-4 mr-1.5" />
                  一次选择两个 JSON 文件（自动识别 API 与配置）
                </Button>
                <span className="text-xs text-muted-foreground">
                  支持 <code>workflow.api.json</code> + <code>jaaz.workflow.json</code> 或{' '}
                  <code>name.api.json</code> + <code>name.jaaz.json</code>
                </span>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3 p-3 border rounded-md bg-muted/20">
                <input
                  ref={draftApiInputRef}
                  type="file"
                  accept=".json"
                  className="hidden"
                  onChange={handlePickDraftApiFile}
                />
                <div className="flex items-center gap-2">
                  <Label htmlFor="draft-name" className="text-xs whitespace-nowrap">
                    工具标识:
                  </Label>
                  <Input
                    id="draft-name"
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    className="h-8 w-44"
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => draftApiInputRef.current?.click()}
                >
                  <Sparkles className="w-4 h-4 mr-1.5" />
                  选择 API JSON 并生成配置草稿
                </Button>
                {configText && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      try {
                        downloadJsonFile('jaaz.workflow.json', JSON.parse(configText))
                      } catch {
                        toast.error('当前配置文本不是合法 JSON')
                      }
                    }}
                  >
                    <Download className="w-4 h-4 mr-1" />
                    下载配置文件
                  </Button>
                )}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>workflow.api.json（ComfyUI API Format）</Label>
              <Textarea
                rows={10}
                value={apiText}
                onChange={(e) => setApiText(e.target.value)}
                placeholder="粘贴或上传 Export (API) 导出的 JSON..."
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label>jaaz.workflow.json（能力与参数映射配置）</Label>
              <Textarea
                rows={10}
                value={configText}
                onChange={(e) => setConfigText(e.target.value)}
                placeholder="粘贴或上传 jaaz.workflow.json..."
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="flex items-center justify-between pt-1">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Switch checked={saveToDir} onCheckedChange={setSaveToDir} />
              <span>同时写入项目 <code>workflows/&lt;name&gt;/</code> 目录长期保存</span>
            </label>
          </div>

          {importError && (
            <div className="p-3 rounded-md bg-red-50 border border-red-200 text-red-700 text-xs whitespace-pre-wrap">
              {importError}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowImportDialog(false)}>
              取消
            </Button>
            <Button onClick={handleSubmitImport} disabled={submittingImport}>
              {submittingImport ? '校验并导入中...' : '校验并导入'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 原地编辑元数据弹窗 */}
      <Dialog open={!!editTarget} onOpenChange={(open) => !open && setEditTarget(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>编辑工作流配置：{editTarget?.name}</DialogTitle>
            <DialogDescription>
              单事务原地更新，保留原始 ID 与历史关联。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>展示名称</Label>
                <Input
                  value={editForm.display_name}
                  onChange={(e) =>
                    setEditForm((prev) => ({ ...prev, display_name: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label>能力分类</Label>
                <Select
                  value={editForm.capability}
                  onValueChange={(val) =>
                    setEditForm((prev) => ({ ...prev, capability: val }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CAPABILITY_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label>输出类型</Label>
                <Select
                  value={editForm.output_kind}
                  onValueChange={(val) =>
                    setEditForm((prev) => ({ ...prev, output_kind: val }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="image">image</SelectItem>
                    <SelectItem value="video">video</SelectItem>
                    <SelectItem value="audio">audio</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>绑定 ComfyUI 实例</Label>
                <Select
                  value={editForm.instance_id || '__auto__'}
                  onValueChange={(val) =>
                    setEditForm((prev) => ({
                      ...prev,
                      instance_id: val === '__auto__' ? '' : val,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__auto__">自动按优先级选择</SelectItem>
                    {instances.map((inst) => (
                      <SelectItem key={inst.id} value={inst.id}>
                        {inst.name} ({inst.id})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>种子策略</Label>
                <Select
                  value={editForm.seed_strategy}
                  onValueChange={(val) =>
                    setEditForm((prev) => ({ ...prev, seed_strategy: val }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="random">random（未指定时随机）</SelectItem>
                    <SelectItem value="fixed">fixed（保留工作流原值）</SelectItem>
                    <SelectItem value="param">param（仅覆盖传参）</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>工具描述（供 Agent 选择工具参考）</Label>
              <Textarea
                rows={4}
                value={editForm.description}
                onChange={(e) =>
                  setEditForm((prev) => ({ ...prev, description: e.target.value }))
                }
              />
            </div>

            <div className="space-y-1.5">
              <Label>输入参数映射 JSON</Label>
              <Textarea
                rows={6}
                className="font-mono text-xs"
                value={editForm.inputsText}
                onChange={(e) =>
                  setEditForm((prev) => ({ ...prev, inputsText: e.target.value }))
                }
              />
            </div>

            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Switch
                checked={editForm.enabled}
                onCheckedChange={(checked) =>
                  setEditForm((prev) => ({ ...prev, enabled: checked }))
                }
              />
              <span>启用（对 Agent 可见）</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditTarget(null)}>
              取消
            </Button>
            <Button onClick={handleSaveEdit}>保存更改</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除工作流</DialogTitle>
            <DialogDescription>
              将从数据库中删除「{deleteTarget?.display_name || deleteTarget?.name}」（不会删除项目{' '}
              <code>workflows/</code> 目录中的文件备份）。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleDeleteWorkflow}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
