import { Input } from '@/components/ui/input'
import React, { lazy, Suspense } from 'react'
import TopMenu from '../TopMenu'

const CanvasStudioDrawer = lazy(() => import('./CanvasStudioDrawer'))
const CanvasLayersAndSnapshotsDrawer = lazy(
  () => import('./CanvasLayersAndSnapshotsDrawer')
)
const CanvasExport = lazy(() => import('./CanvasExport'))

type CanvasHeaderProps = {
  canvasName: string
  canvasId: string
  onNameChange: (name: string) => void
  onNameSave: () => void
}

const CanvasHeader: React.FC<CanvasHeaderProps> = ({
  canvasName,
  canvasId,
  onNameChange,
  onNameSave,
}) => {
  return (
    <TopMenu
      middle={
        <Input
          className="text-sm text-muted-foreground text-center bg-transparent border-none shadow-none w-fit h-7 hover:bg-primary-foreground transition-all"
          value={canvasName}
          onChange={(e) => onNameChange(e.target.value)}
          onBlur={onNameSave}
        />
      }
      right={
        <div className="flex items-center gap-2">
          <Suspense fallback={null}>
            <CanvasStudioDrawer canvasId={canvasId} />
            <CanvasLayersAndSnapshotsDrawer canvasId={canvasId} />
            <CanvasExport />
          </Suspense>
        </div>
      }
    />
  )
}

export default CanvasHeader
