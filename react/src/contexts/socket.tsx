/** 程序说明：管理同源 Socket.IO 连接上下文及生命周期事件监听清理。 */
import { SocketIOManager } from '@/lib/socket'
import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface SocketContextType {
  connected: boolean
  socketId?: string
  connecting: boolean
  error?: string
  socketManager: SocketIOManager | null
}

const SocketContext = createContext<SocketContextType>({
  connected: false,
  connecting: false,
  socketManager: null,
})

interface SocketProviderProps {
  children: React.ReactNode
}

export const SocketProvider: React.FC<SocketProviderProps> = ({ children }) => {
  const { t } = useTranslation()
  const [connected, setConnected] = useState(false)
  const [socketId, setSocketId] = useState<string>()
  const [connecting, setConnecting] = useState(true)
  const [error, setError] = useState<string>()

  const socketManagerRef = useRef<SocketIOManager | null>(null)

  useEffect(() => {
    let mounted = true
    let cleanupListeners: (() => void) | undefined

    const initializeSocket = async () => {
      try {
        setConnecting(true)
        setError(undefined)

        if (!socketManagerRef.current) {
          // 统一使用当前同源 origin，开发模式走 Vite /socket.io 代理，保证鉴权 Cookie 同源携带
          socketManagerRef.current = new SocketIOManager({
            serverUrl: window.location.origin,
            autoConnect: false,
          })
        }

        const socketManager = socketManagerRef.current
        await socketManager.connect()

        if (!mounted) {
          socketManager.disconnect()
          return
        }

        setConnected(true)
        setSocketId(socketManager.getSocketId())
        setConnecting(false)
        console.log('🚀 Socket.IO initialized successfully')

        const socket = socketManager.getSocket()
        if (socket) {
          const handleConnect = () => {
            if (mounted) {
              setConnected(true)
              setSocketId(socketManager.getSocketId())
              setConnecting(false)
              setError(undefined)
            }
          }

          const handleDisconnect = () => {
            if (mounted) {
              setConnected(false)
              setSocketId(undefined)
              setConnecting(false)
            }
          }

          const handleConnectError = (connError: Error) => {
            if (mounted) {
              setError(connError.message || '❌ Socket.IO Connection Error')
              setConnected(false)
              setConnecting(false)
            }
          }

          socket.on('connect', handleConnect)
          socket.on('disconnect', handleDisconnect)
          socket.on('connect_error', handleConnectError)

          cleanupListeners = () => {
            socket.off('connect', handleConnect)
            socket.off('disconnect', handleDisconnect)
            socket.off('connect_error', handleConnectError)
          }
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Unknown error')
          setConnected(false)
          setConnecting(false)
          console.error('❌ Failed to initialize Socket.IO:', err)
        }
      }
    }

    void initializeSocket()

    return () => {
      mounted = false
      cleanupListeners?.()
      if (socketManagerRef.current) {
        socketManagerRef.current.disconnect()
        socketManagerRef.current = null
      }
    }
  }, [])

  const value: SocketContextType = {
    connected,
    socketId,
    connecting,
    error,
    socketManager: socketManagerRef.current,
  }

  return (
    <SocketContext.Provider value={value}>
      {children}

      {error && (
        <div className="fixed top-4 right-4 z-50 bg-red-500 text-white px-3 py-2 rounded-md shadow-lg">
          {socketManagerRef.current?.isMaxReconnectAttemptsReached()
            ? t('socket.maxRetriesReached')
            : t('socket.connectionError', {
                current: socketManagerRef.current?.getReconnectAttempts() || 0,
                max: 5,
                error,
              })}
        </div>
      )}
    </SocketContext.Provider>
  )
}

export { SocketContext }
export const useSocket = () => useContext(SocketContext)
