import { getChatSession, sendMessages } from '@/api/chat'
import Blur from '@/components/common/Blur'
import { ScrollArea } from '@/components/ui/scroll-area'
import { eventBus, TEvents } from '@/lib/event'
import { TaskStatusSnapshot } from '@/lib/chatTaskProgress'
import {
  AssistantMessage,
  Message,
  Model,
  PendingType,
  Session,
} from '@/types/types'
import { useSearch } from '@tanstack/react-router'
import { produce } from 'immer'
import { motion } from 'motion/react'
import { nanoid } from 'nanoid'
import {
  Dispatch,
  SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useTranslation } from 'react-i18next'
import { PhotoProvider } from 'react-photo-view'
import { toast } from 'sonner'
import ShinyText from '../ui/shiny-text'
import ChatTextarea from './ChatTextarea'
import MessageRegular from './Message/Regular'
import { ToolCallContent } from './Message/ToolCallContent'
import ToolCallTag from './Message/ToolCallTag'
import SessionSelector from './SessionSelector'
import ChatSpinner from './Spinner'
import ToolcallProgressUpdate from './ToolcallProgressUpdate'

import { useConfigs } from '@/contexts/configs'
import 'react-photo-view/dist/react-photo-view.css'
import { DEFAULT_SYSTEM_PROMPT } from '@/constants'
import { ModelInfo, ToolInfo } from '@/api/model'
import MixedContent, { MixedContentImages, MixedContentText } from './Message/MixedContent'


type ChatInterfaceProps = {
  canvasId: string
  sessionList: Session[]
  setSessionList: Dispatch<SetStateAction<Session[]>>
  sessionId: string
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({
  canvasId,
  sessionList,
  setSessionList,
  sessionId: searchSessionId,
}) => {
  const { t } = useTranslation()
  const [session, setSession] = useState<Session | null>(null)
  const { initCanvas, setInitCanvas } = useConfigs()

  useEffect(() => {
    if (sessionList.length > 0) {
      let _session = null
      if (searchSessionId) {
        _session = sessionList.find((s) => s.id === searchSessionId) || null
      } else {
        _session = sessionList[0]
      }
      setSession(_session)
    } else {
      setSession(null)
    }
  }, [sessionList, searchSessionId])

  const [messages, setMessages] = useState<Message[]>([])
  const [pending, setPending] = useState<PendingType>(
    initCanvas ? 'text' : false
  )
  const [taskSessionId, setTaskSessionId] = useState<string | null>(null)
  const mergedToolCallIds = useRef<string[]>([])

  const sessionId = session?.id ?? searchSessionId

  const sessionIdRef = useRef<string>(session?.id || nanoid())
  const [expandingToolCalls, setExpandingToolCalls] = useState<string[]>([])
  const [pendingToolConfirmations, setPendingToolConfirmations] = useState<
    string[]
  >([])

  const scrollRef = useRef<HTMLDivElement>(null)
  const isAtBottomRef = useRef(false)

  const scrollToBottom = useCallback(() => {
    if (!isAtBottomRef.current) {
      return
    }
    setTimeout(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current!.scrollHeight,
        behavior: 'smooth',
      })
    }, 200)
  }, [])

  const mergeToolCallResult = useCallback((messages: Message[]) => {
    const messagesWithToolCallResult = messages.map((message, index) => {
      if (message.role === 'assistant' && message.tool_calls) {
        for (const toolCall of message.tool_calls) {
          // From the next message, find the tool call result
          for (let i = index + 1; i < messages.length; i++) {
            const nextMessage = messages[i]
            if (
              nextMessage.role === 'tool' &&
              nextMessage.tool_call_id === toolCall.id
            ) {
              toolCall.result = nextMessage.content
              mergedToolCallIds.current.push(toolCall.id)
            }
          }
        }
      }
      return message
    })

    return messagesWithToolCallResult
  }, [])

  const handleDelta = useCallback(
    (data: TEvents['Socket::Session::Delta']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      setPending('text')
      setMessages(
        produce((prev) => {
          const last = prev.at(-1)
          if (
            last?.role === 'assistant' &&
            last.content != null &&
            last.tool_calls == null
          ) {
            if (typeof last.content === 'string') {
              last.content += data.text
            } else if (
              last.content &&
              last.content.at(-1) &&
              last.content.at(-1)!.type === 'text'
            ) {
              ;(last.content.at(-1) as { text: string }).text += data.text
            }
          } else {
            prev.push({
              role: 'assistant',
              content: data.text,
            })
          }
        })
      )
      scrollToBottom()
    },
    [sessionId, scrollToBottom]
  )

  const handleToolCall = useCallback(
    (data: TEvents['Socket::Session::ToolCall']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      // 将去重校验放入 reducer 内以基于最新消息快照判断，同时避免在 produce 内产生副作用
      setPending('tool')
      setMessages(
        produce((prev) => {
          const existToolCall = prev.some(
            (m) =>
              m.role === 'assistant' &&
              m.tool_calls &&
              m.tool_calls.some((t) => t.id == data.id)
          )
          if (existToolCall) {
            return
          }
          console.log('👇tool_call event get', data)
          prev.push({
            role: 'assistant',
            content: '',
            tool_calls: [
              {
                type: 'function',
                function: {
                  name: data.name,
                  arguments: '',
                },
                id: data.id,
              },
            ],
          })
        })
      )

      setExpandingToolCalls(
        produce((prev) => {
          if (!prev.includes(data.id)) {
            prev.push(data.id)
          }
        })
      )
    },
    [sessionId]
  )

  const handleToolCallPendingConfirmation = useCallback(
    (data: TEvents['Socket::Session::ToolCallPendingConfirmation']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      setPending('tool')
      setMessages(
        produce((prev) => {
          const existToolCall = prev.some(
            (m) =>
              m.role === 'assistant' &&
              m.tool_calls &&
              m.tool_calls.some((t) => t.id == data.id)
          )
          if (existToolCall) {
            return
          }
          console.log('👇tool_call_pending_confirmation event get', data)
          prev.push({
            role: 'assistant',
            content: '',
            tool_calls: [
              {
                type: 'function',
                function: {
                  name: data.name,
                  arguments: data.arguments,
                },
                id: data.id,
              },
            ],
          })
        })
      )

      setPendingToolConfirmations(
        produce((prev) => {
          if (!prev.includes(data.id)) {
            prev.push(data.id)
          }
        })
      )

      // 自动展开需要确认的工具调用
      setExpandingToolCalls(
        produce((prev) => {
          if (!prev.includes(data.id)) {
            prev.push(data.id)
          }
        })
      )
    },
    [sessionId]
  )

  const handleToolCallConfirmed = useCallback(
    (data: TEvents['Socket::Session::ToolCallConfirmed']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      setPendingToolConfirmations(
        produce((prev) => {
          return prev.filter((id) => id !== data.id)
        })
      )

      setExpandingToolCalls(
        produce((prev) => {
          if (!prev.includes(data.id)) {
            prev.push(data.id)
          }
        })
      )
    },
    [sessionId]
  )

  const handleToolCallCancelled = useCallback(
    (data: TEvents['Socket::Session::ToolCallCancelled']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      setPendingToolConfirmations(
        produce((prev) => {
          return prev.filter((id) => id !== data.id)
        })
      )

      // 更新工具调用的状态
      setMessages(
        produce((prev) => {
          prev.forEach((msg) => {
            if (msg.role === 'assistant' && msg.tool_calls) {
              msg.tool_calls.forEach((tc) => {
                if (tc.id === data.id) {
                  // 添加取消状态标记
                  tc.result = '工具调用已取消'
                }
              })
            }
          })
        })
      )
    },
    [sessionId]
  )

  const handleToolCallArguments = useCallback(
    (data: TEvents['Socket::Session::ToolCallArguments']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      setPending('tool')
      setMessages(
        produce((prev) => {
          const lastMessage = prev.find(
            (m) =>
              m.role === 'assistant' &&
              m.tool_calls &&
              m.tool_calls.find((t) => t.id == data.id)
          ) as AssistantMessage

          if (lastMessage) {
            const toolCall = lastMessage.tool_calls!.find(
              (t) => t.id == data.id
            )
            if (toolCall) {
              // 检查是否是待确认的工具调用，如果是则跳过参数追加
              if (pendingToolConfirmations.includes(data.id)) {
                return
              }
              toolCall.function.arguments += data.text
            }
          }
        })
      )
      scrollToBottom()
    },
    [sessionId, scrollToBottom, pendingToolConfirmations]
  )

  const handleToolCallResult = useCallback(
    (data: TEvents['Socket::Session::ToolCallResult']) => {
      console.log('😘🖼️tool_call_result event get', data)
      if (data.session_id && data.session_id !== sessionId) {
        return
      }
      // TODO: support other non string types of returning content like image_url
      if (data.message.content) {
        setMessages(
          produce((prev) => {
            prev.forEach((m) => {
              if (m.role === 'assistant' && m.tool_calls) {
                m.tool_calls.forEach((t) => {
                  if (t.id === data.id) {
                    t.result = data.message.content
                  }
                })
              }
            })
          })
        )
      }
    },
    [canvasId, sessionId]
  )

  const handleImageGenerated = useCallback(
    (data: TEvents['Socket::Session::ImageGenerated']) => {
      if (
        data.canvas_id &&
        data.canvas_id !== canvasId &&
        data.session_id !== sessionId
      ) {
        return
      }

      console.log('⭐️dispatching image_generated', data)
      setPending('image')
    },
    [canvasId, sessionId]
  )

  const handleAllMessages = useCallback(
    (data: TEvents['Socket::Session::AllMessages']) => {
      if (data.session_id && data.session_id !== sessionId) {
        return
      }

      setMessages(() => {
        console.log('👇all_messages', data.messages)
        return data.messages
      })
      setMessages(mergeToolCallResult(data.messages))
      scrollToBottom()
    },
    [sessionId, scrollToBottom]
  )

  const handleDone = useCallback(
    (data: TEvents['Socket::Session::Done']) => {
      const activeSessionId = taskSessionId || sessionId
      if (data.session_id && data.session_id !== activeSessionId) {
        return
      }

      setPending(false)
      setTaskSessionId(null)
      scrollToBottom()

    },
    [sessionId, scrollToBottom, taskSessionId]
  )

  const handleError = useCallback(
    (data: TEvents['Socket::Session::Error']) => {
      const activeSessionId = taskSessionId || sessionId
      if (data.session_id && data.session_id !== activeSessionId) {
        return
      }

      setPending(false)
      setTaskSessionId(null)
      toast.error('Error: ' + data.error, {
        closeButton: true,
        duration: 3600 * 1000,
        style: { color: 'red' },
      })
    },
    [sessionId, taskSessionId]
  )

  const handleRecoveredTaskFinished = useCallback(
    async (status: TaskStatusSnapshot) => {
      const finishedSessionId = taskSessionId || sessionId
      try {
        if (finishedSessionId) {
          const savedMessages = await getChatSession(finishedSessionId)
          setMessages(mergeToolCallResult(savedMessages))
        }
        eventBus.emit('Canvas::SyncGeneratedImages', { canvasId })

        if (status.terminal_state === 'failed') {
          toast.error('Error: ' + (status.error || 'Task failed'))
        } else if (status.terminal_state === 'unknown') {
          toast.info('Connection was interrupted. Saved results were restored.')
        }
      } catch (error) {
        console.error('Could not restore completed chat results', error)
        toast.error('Could not reload completed task results')
      } finally {
        setPending(false)
        setTaskSessionId(null)
        scrollToBottom()
      }
    },
    [canvasId, mergeToolCallResult, scrollToBottom, sessionId, taskSessionId]
  )

  const handleInfo = useCallback((data: TEvents['Socket::Session::Info']) => {
    toast.info(data.info, {
      closeButton: true,
      duration: 10 * 1000,
    })
  }, [])

  // 使用 ref 持有最新事件处理器，确保 12 个 eventBus 监听在挂载期间只绑定和清理一次
  const handlersRef = useRef({
    handleDelta,
    handleToolCall,
    handleToolCallPendingConfirmation,
    handleToolCallConfirmed,
    handleToolCallCancelled,
    handleToolCallArguments,
    handleToolCallResult,
    handleImageGenerated,
    handleAllMessages,
    handleDone,
    handleError,
    handleInfo,
  })
  handlersRef.current = {
    handleDelta,
    handleToolCall,
    handleToolCallPendingConfirmation,
    handleToolCallConfirmed,
    handleToolCallCancelled,
    handleToolCallArguments,
    handleToolCallResult,
    handleImageGenerated,
    handleAllMessages,
    handleDone,
    handleError,
    handleInfo,
  }

  useEffect(() => {
    const handleScroll = () => {
      if (scrollRef.current) {
        isAtBottomRef.current =
          scrollRef.current.scrollHeight - scrollRef.current.scrollTop <=
          scrollRef.current.clientHeight + 1
      }
    }
    const scrollEl = scrollRef.current
    scrollEl?.addEventListener('scroll', handleScroll)

    const onDelta = (d: TEvents['Socket::Session::Delta']) => handlersRef.current.handleDelta(d)
    const onToolCall = (d: TEvents['Socket::Session::ToolCall']) => handlersRef.current.handleToolCall(d)
    const onToolCallPendingConfirmation = (d: TEvents['Socket::Session::ToolCallPendingConfirmation']) =>
      handlersRef.current.handleToolCallPendingConfirmation(d)
    const onToolCallConfirmed = (d: TEvents['Socket::Session::ToolCallConfirmed']) =>
      handlersRef.current.handleToolCallConfirmed(d)
    const onToolCallCancelled = (d: TEvents['Socket::Session::ToolCallCancelled']) =>
      handlersRef.current.handleToolCallCancelled(d)
    const onToolCallArguments = (d: TEvents['Socket::Session::ToolCallArguments']) =>
      handlersRef.current.handleToolCallArguments(d)
    const onToolCallResult = (d: TEvents['Socket::Session::ToolCallResult']) =>
      handlersRef.current.handleToolCallResult(d)
    const onImageGenerated = (d: TEvents['Socket::Session::ImageGenerated']) =>
      handlersRef.current.handleImageGenerated(d)
    const onAllMessages = (d: TEvents['Socket::Session::AllMessages']) =>
      handlersRef.current.handleAllMessages(d)
    const onDone = (d: TEvents['Socket::Session::Done']) => handlersRef.current.handleDone(d)
    const onError = (d: TEvents['Socket::Session::Error']) => handlersRef.current.handleError(d)
    const onInfo = (d: TEvents['Socket::Session::Info']) => handlersRef.current.handleInfo(d)

    eventBus.on('Socket::Session::Delta', onDelta)
    eventBus.on('Socket::Session::ToolCall', onToolCall)
    eventBus.on('Socket::Session::ToolCallPendingConfirmation', onToolCallPendingConfirmation)
    eventBus.on('Socket::Session::ToolCallConfirmed', onToolCallConfirmed)
    eventBus.on('Socket::Session::ToolCallCancelled', onToolCallCancelled)
    eventBus.on('Socket::Session::ToolCallArguments', onToolCallArguments)
    eventBus.on('Socket::Session::ToolCallResult', onToolCallResult)
    eventBus.on('Socket::Session::ImageGenerated', onImageGenerated)
    eventBus.on('Socket::Session::AllMessages', onAllMessages)
    eventBus.on('Socket::Session::Done', onDone)
    eventBus.on('Socket::Session::Error', onError)
    eventBus.on('Socket::Session::Info', onInfo)
    return () => {
      scrollEl?.removeEventListener('scroll', handleScroll)

      eventBus.off('Socket::Session::Delta', onDelta)
      eventBus.off('Socket::Session::ToolCall', onToolCall)
      eventBus.off('Socket::Session::ToolCallPendingConfirmation', onToolCallPendingConfirmation)
      eventBus.off('Socket::Session::ToolCallConfirmed', onToolCallConfirmed)
      eventBus.off('Socket::Session::ToolCallCancelled', onToolCallCancelled)
      eventBus.off('Socket::Session::ToolCallArguments', onToolCallArguments)
      eventBus.off('Socket::Session::ToolCallResult', onToolCallResult)
      eventBus.off('Socket::Session::ImageGenerated', onImageGenerated)
      eventBus.off('Socket::Session::AllMessages', onAllMessages)
      eventBus.off('Socket::Session::Done', onDone)
      eventBus.off('Socket::Session::Error', onError)
      eventBus.off('Socket::Session::Info', onInfo)
    }
  }, [])

  const initChat = useCallback(async () => {
    if (!sessionId) {
      return
    }

    sessionIdRef.current = sessionId

    const resp = await fetch('/api/chat_session/' + sessionId)
    const data = await resp.json()
    const msgs = data?.length ? data : []

    setMessages(mergeToolCallResult(msgs))
    if (msgs.length > 0) {
      setInitCanvas(false)
    }

    scrollToBottom()
  }, [mergeToolCallResult, sessionId, scrollToBottom, setInitCanvas])

  useEffect(() => {
    initChat()
  }, [sessionId, initChat])

  const onSelectSession = (sessionId: string) => {
    sessionIdRef.current = sessionId
    setSession(sessionList.find((s) => s.id === sessionId) || null)
    window.history.pushState(
      {},
      '',
      `/canvas/${canvasId}?sessionId=${sessionId}`
    )
  }

  const onClickNewChat = () => {
    const newSession: Session = {
      id: nanoid(),
      title: t('chat:newChat'),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      model: session?.model || 'gpt-4o',
      provider: session?.provider || 'openai',
    }

    sessionIdRef.current = newSession.id
    setSessionList((prev) => [...prev, newSession])
    onSelectSession(newSession.id)
  }

  const onSendMessages = useCallback(
    (data: Message[], configs: { textModel: Model; toolList: ToolInfo[] }) => {
      const activeSessionId = sessionId || sessionIdRef.current || nanoid()
      sessionIdRef.current = activeSessionId
      setTaskSessionId(activeSessionId)
      setPending('text')
      setMessages(data)

      if (!sessionId) {
        const newSession: Session = {
          id: activeSessionId,
          title: t('chat:newChat'),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          model: configs.textModel.model || 'gpt-4o',
          provider: configs.textModel.provider || 'openai',
        }
        setSession(newSession)
        setSessionList((prev) =>
          prev.some((item) => item.id === activeSessionId)
            ? prev
            : [...prev, newSession]
        )
      }

      void sendMessages({
        sessionId: activeSessionId,
        canvasId: canvasId,
        newMessages: data,
        textModel: configs.textModel,
        toolList: configs.toolList,
        systemPrompt:
          localStorage.getItem('system_prompt') || DEFAULT_SYSTEM_PROMPT,
      }).catch((error: unknown) => {
        console.error('Failed to submit chat task', error)
        if (sessionIdRef.current === activeSessionId) {
          setPending(false)
          setTaskSessionId(null)
          toast.error(
            `Could not start task: ${error instanceof Error ? error.message : String(error)}`,
            { closeButton: true }
          )
        }
      })

      if (searchSessionId !== activeSessionId) {
        window.history.pushState(
          {},
          '',
          `/canvas/${canvasId}?sessionId=${activeSessionId}`
        )
      }

      scrollToBottom()
    },
    [canvasId, sessionId, searchSessionId, scrollToBottom, setSessionList, t]
  )

  const handleCancelChat = useCallback(() => {
    setPending(false)
  }, [])

  return (
    <PhotoProvider>
      <div className='flex flex-col h-screen relative'>
        {/* Chat messages */}

        <header className='flex items-center px-2 py-2 absolute top-0 z-1 w-full'>
          <div className='flex-1 min-w-0'>
            <SessionSelector
              session={session}
              sessionList={sessionList}
              onClickNewChat={onClickNewChat}
              onSelectSession={onSelectSession}
            />
          </div>

          {/* Share Template Button */}

          <Blur className='absolute top-0 left-0 right-0 h-full -z-1' />
        </header>

        <ScrollArea className='h-[calc(100vh-45px)]' viewportRef={scrollRef}>
          {messages.length > 0 ? (
            <div className='flex flex-col flex-1 px-4 pb-50 pt-15'>
              {/* Messages */}
              {messages.map((message, idx) => (
                <div key={`${idx}`} className='flex flex-col gap-4 mb-2'>
                  {/* Regular message content */}
                  {typeof message.content == 'string' &&
                    (message.role !== 'tool' ? (
                      <MessageRegular
                        message={message}
                        content={message.content}
                      />
                    ) : message.tool_call_id &&
                      mergedToolCallIds.current.includes(
                        message.tool_call_id
                      ) ? (
                      <></>
                    ) : (
                      <ToolCallContent
                        expandingToolCalls={expandingToolCalls}
                        message={message}
                      />
                    ))}

                  {/* 混合内容消息的文本部分 - 显示在聊天框内 */}
                  {Array.isArray(message.content) && (
                    <>
                      <MixedContentImages
                        contents={message.content}
                      />
                      <MixedContentText
                        message={message}
                        contents={message.content}
                      />
                    </>
                  )}

                  {message.role === 'assistant' &&
                    message.tool_calls &&
                    message.tool_calls.at(-1)?.function.name != 'finish' &&
                    message.tool_calls.map((toolCall, i) => {
                      return (
                        <ToolCallTag
                          key={toolCall.id}
                          toolCall={toolCall}
                          isExpanded={expandingToolCalls.includes(toolCall.id)}
                          onToggleExpand={() => {
                            if (expandingToolCalls.includes(toolCall.id)) {
                              setExpandingToolCalls((prev) =>
                                prev.filter((id) => id !== toolCall.id)
                              )
                            } else {
                              setExpandingToolCalls((prev) => [
                                ...prev,
                                toolCall.id,
                              ])
                            }
                          }}
                          requiresConfirmation={pendingToolConfirmations.includes(
                            toolCall.id
                          )}
                          onConfirm={() => {
                            // 发送确认事件到后端
                            fetch('/api/tool_confirmation', {
                              method: 'POST',
                              headers: {
                                'Content-Type': 'application/json',
                              },
                              body: JSON.stringify({
                                session_id: sessionId,
                                tool_call_id: toolCall.id,
                                confirmed: true,
                              }),
                            })
                          }}
                          onCancel={() => {
                            // 发送取消事件到后端
                            fetch('/api/tool_confirmation', {
                              method: 'POST',
                              headers: {
                                'Content-Type': 'application/json',
                              },
                              body: JSON.stringify({
                                session_id: sessionId,
                                tool_call_id: toolCall.id,
                                confirmed: false,
                              }),
                            })
                          }}
                        />
                      )
                    })}
                </div>
              ))}
              {pending && <ChatSpinner pending={pending} />}
              {pending && (
                <ToolcallProgressUpdate
                  sessionId={taskSessionId || sessionId || ''}
                  onTaskFinished={handleRecoveredTaskFinished}
                />
              )}
            </div>
          ) : (
            <motion.div className='flex flex-col h-full p-4 items-start justify-start pt-16 select-none'>
              <motion.span
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className='text-muted-foreground text-3xl'
              >
                <ShinyText text='Hello, Jaaz!' />
              </motion.span>
              <motion.span
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6 }}
                className='text-muted-foreground text-2xl'
              >
                <ShinyText text='How can I help you today?' />
              </motion.span>
            </motion.div>
          )}
        </ScrollArea>

        <div className='p-2 gap-2 sticky bottom-0'>
          <ChatTextarea
            sessionId={sessionId!}
            pending={!!pending}
            messages={messages}
            onSendMessages={onSendMessages}
            onCancelChat={handleCancelChat}
          />
        </div>
      </div>
    </PhotoProvider>
  )
}

export default ChatInterface
