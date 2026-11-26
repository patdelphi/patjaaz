import ErrorBoundary from '@/components/common/ErrorBoundary'
import { createRootRoute, Outlet } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'

const RouterDevtools = import.meta.env.DEV
  ? lazy(() =>
      import('@tanstack/react-router-devtools').then((m) => ({
        default: m.TanStackRouterDevtools,
      }))
    )
  : () => null

export const Route = createRootRoute({
  component: () => (
    <>
      <Outlet />
      <Suspense fallback={null}>
        <RouterDevtools />
      </Suspense>
    </>
  ),
  errorComponent: ErrorBoundary,
})
