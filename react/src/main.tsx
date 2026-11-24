/** 程序说明：应用挂载入口，首先安装统一 401 鉴权拦截器，再渲染 AuthGate 与主界面。 */
import { AuthGate } from '@/components/auth/AuthGate'
import { SocketProvider } from '@/contexts/socket'
import { installApiAuthInterceptor } from '@/lib/apiFetch'
import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { PostHogProvider } from 'posthog-js/react'
import '@/assets/style/index.css'

installApiAuthInterceptor()

const options = {
  api_host: import.meta.env.VITE_PUBLIC_POSTHOG_HOST,
}

const rootElement = document.getElementById('root')!
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement)
  root.render(
    <StrictMode>
      <AuthGate>
        <PostHogProvider apiKey={import.meta.env.VITE_PUBLIC_POSTHOG_KEY} options={options}>
          <SocketProvider>
            <App />
          </SocketProvider>
        </PostHogProvider>
      </AuthGate>
    </StrictMode>
  )
}
