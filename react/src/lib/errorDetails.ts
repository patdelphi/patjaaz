// 将未知异常安全转换为可显示的错误信息。
export type ErrorDetails = {
  name: string
  message: string
  stack: string
}

export function getErrorDetails(error: unknown): ErrorDetails {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack ?? '',
    }
  }

  if (error !== null && typeof error === 'object') {
    const value = error as { name?: unknown; message?: unknown; stack?: unknown }
    return {
      name: typeof value.name === 'string' ? value.name : 'Unknown Error',
      message: typeof value.message === 'string' ? value.message : String(error),
      stack: typeof value.stack === 'string' ? value.stack : '',
    }
  }

  return { name: 'Unknown Error', message: String(error), stack: '' }
}
