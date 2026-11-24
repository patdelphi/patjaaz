/** 程序说明：应用挂载入口，首先安装统一 401 鉴权拦截器，再渲染 AuthGate 与主界面。 */
import { AuthGate } from '@/components/auth/AuthGate'
import { SocketProvider } from '@/contexts/socket'
import { installApiAuthInterceptor } from '@/lib/apiFetch'
import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import '@/assets/style/index.css'

installApiAuthInterceptor()

const rootElement = document.getElementById('root')!
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement)
  root.render(
    <StrictMode>
      <AuthGate>
        <SocketProvider>
          <App />
        </SocketProvider>
      </AuthGate>
    </StrictMode>
  )
}
