/* 程序说明：在应用与 Socket.IO 启动前完成单一登录码校验，并在会话过期或返回 401 时切回锁屏状态。 */
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import '@/i18n'
import { eventBus } from '@/lib/event'
import { LoaderCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

type GateState = 'checking' | 'locked' | 'authorized' | 'unavailable'

type AuthGateProps = {
  children: ReactNode
}

export function AuthGate({ children }: AuthGateProps) {
  const { t } = useTranslation('common')
  const [state, setState] = useState<GateState>('checking')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const checkStatus = useCallback(async () => {
    setState('checking')
    setError('')
    try {
      const response = await fetch('/api/auth/status')
      if (!response.ok) throw new Error(t('auth.unavailable'))
      const status = await response.json()
      setState(!status.enabled || status.authenticated ? 'authorized' : 'locked')
    } catch {
      setState('unavailable')
      setError(t('auth.unavailable'))
    }
  }, [t])

  useEffect(() => {
    void checkStatus()
  }, [checkStatus])

  useEffect(() => {
    // 任意受保护 API 收到 401 时立即切回锁屏并卸载 SocketProvider 停止重连
    const handleUnauthorized = () => {
      setState((prev) => {
        if (prev === 'locked') return prev
        setError(t('auth.sessionExpired'))
        return 'locked'
      })
    }
    eventBus.on('Auth::Unauthorized', handleUnauthorized)
    return () => {
      eventBus.off('Auth::Unauthorized', handleUnauthorized)
    }
  }, [t])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!code.trim() || isSubmitting) return

    setIsSubmitting(true)
    setError('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
      if (response.status === 429) {
        setError(t('auth.rateLimited'))
        return
      }
      if (response.status === 401) {
        setError(t('auth.invalid'))
        return
      }
      if (!response.ok) throw new Error(t('auth.unavailable'))
      setState('authorized')
      setCode('')
    } catch {
      setError(t('auth.unavailable'))
    } finally {
      setIsSubmitting(false)
    }
  }

  if (state === 'authorized') return <>{children}</>

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 text-foreground">
      <section className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-lg">
        <h1 className="text-2xl font-semibold">{t('auth.title')}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{t('auth.description')}</p>

        {state === 'checking' ? (
          <div className="mt-6 flex justify-center" aria-label={t('buttons.loading')}>
            <LoaderCircle className="h-5 w-5 animate-spin" />
          </div>
        ) : state === 'unavailable' ? (
          <div className="mt-6 space-y-3">
            <p role="alert" className="text-sm text-destructive">{error}</p>
            <Button className="w-full" onClick={() => void checkStatus()}>
              {t('auth.retry')}
            </Button>
          </div>
        ) : (
          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <label className="block space-y-2 text-sm font-medium" htmlFor="jaaz-access-code">
              <span>{t('auth.code')}</span>
              <Input
                id="jaaz-access-code"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button className="w-full" type="submit" disabled={isSubmitting || !code.trim()}>
              {isSubmitting ? t('buttons.loading') : t('auth.submit')}
            </Button>
          </form>
        )}
      </section>
    </main>
  )
}
