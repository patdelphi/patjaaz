// electron/main.js
// npx electron electron/main.js

const fs = require('fs')
const path = require('path')
const os = require('os')
// to import a ts module, we need to import like below
// const gemini = require('./dist/gemin_service')
const logPath = path.join(os.homedir(), 'jaaz-log.txt')
// Check if the log file exists and delete it
if (fs.existsSync(logPath)) {
  fs.unlinkSync(logPath)
}

const logStream = fs.createWriteStream(logPath, { flags: 'a' })

// Redirect all stdout and stderr to the log file
process.stdout.write = process.stderr.write = logStream.write.bind(logStream)

// Optional: Add timestamps to log output
const origLog = console.log
console.log = (...args) => {
  const time = new Date().toISOString()
  origLog(`[${time}]`, ...args)
}

console.error = (...args) => {
  const time = new Date().toISOString()
  origLog(`[${time}][ERROR]`, ...args)
}

// Initial log entry
console.log('🟢 Jaaz Electron app starting...')

const { app, BrowserWindow, ipcMain, dialog, session } = require('electron')
const { spawn } = require('child_process')

const net = require('net')

const DEFAULT_API_PORT = 57988

// Initialize settings service
const settingsService = require('./settingsService')

function findAvailablePort(startPort, maxAttempts = 100) {
  return new Promise((resolve, reject) => {
    let attempts = 0

    const tryPort = (port) => {
      attempts++
      if (attempts > maxAttempts) {
        reject(new Error(`Could not find available port after ${maxAttempts} attempts`))
        return
      }

      const server = net.createServer()

      server.on('error', (err) => {
        if (err.code === 'EADDRINUSE') {
          console.log(`Port ${port} is in use, trying next port...`)
          server.close()
          tryPort(port + 1)
        } else {
          reject(err)
        }
      })

      // 明确指定 host 为 127.0.0.1，确保检测到端口占用
      server.listen(port, '127.0.0.1', () => {
        server.close(() => {
          console.log(`Found available port: ${port}`)
          resolve(port)
        })
      })
    }

    tryPort(startPort)
  })
}

let mainWindow
let pyProc = null
let pyPort = null
let pyStartError = null
let childWindows = [] // Track all child windows

const createWindow = (pyPort) => {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    icon: path.join(__dirname, '../assets/icons/jaaz.png'), // ✅ Use .png for dev
    autoHideMenuBar: true, // Hide menu bar (can be toggled with Alt key)
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  })

  // Handle window closed event
  mainWindow.on('closed', () => {
    // Close all child windows
    childWindows.forEach((window) => {
      if (!window.isDestroyed()) {
        window.close()
      }
    })
    childWindows = []
    mainWindow = null
  })

  // Handle all navigation requests (intercept all link clicks)
  // 主要用于处理视频链接导致的页面跳转
  mainWindow.webContents.on('will-navigate', (event, navigationUrl) => {
    console.log('Navigation requested:', navigationUrl)
    event.preventDefault()

    // Create new window for external links
    const newWindow = new BrowserWindow({
      width: 800,
      height: 600,
      title: 'Jaaz Preview',
      icon: path.join(__dirname, '../assets/icons/jaaz.png'),
      autoHideMenuBar: true,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        webSecurity: true,
      },
    })
    newWindow.loadURL(navigationUrl)

    // Add to child windows array
    childWindows.push(newWindow)

    // Handle new window closed event
    newWindow.on('closed', () => {
      // Remove from child windows array
      const index = childWindows.indexOf(newWindow)
      if (index > -1) {
        childWindows.splice(index, 1)
      }
    })
  })

  // In development, use Vite dev server
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5174', {
      extraHeaders: 'pragma: no-cache\n',
    })
    mainWindow.webContents.openDevTools()
  } else {
    // In production, load built files
    mainWindow.loadURL(`http://127.0.0.1:${pyPort}`, {
      extraHeaders: 'pragma: no-cache\n',
    })
  }
}

// 获取 app.asar 内部的根路径
const appRoot = app.getAppPath()

const startPythonApi = async () => {
  const isDevelopment = process.env.NODE_ENV === 'development'

  // 开发模式固定使用 Vite 和 Socket.IO 约定的端口；只复用 Jaaz 后端。
  if (isDevelopment) {
    try {
      // 用公开状态接口识别已启用登录保护的 Jaaz 后端。
      const response = await fetch('http://127.0.0.1:' + DEFAULT_API_PORT + '/api/auth/status', {
        signal: AbortSignal.timeout(1500),
      })
      const payload = response.ok ? await response.json() : null
      if (payload?.enabled === true) {
        pyPort = DEFAULT_API_PORT
        console.log('Reusing Jaaz backend on port:', pyPort)
        return pyPort
      }
    } catch (error) {
      console.log('No ready Jaaz backend on the development port')
    }
  }

  pyPort = await findAvailablePort(DEFAULT_API_PORT)
  if (isDevelopment && pyPort !== DEFAULT_API_PORT) {
    throw new Error('Port ' + DEFAULT_API_PORT + ' is occupied by a service that is not Jaaz.')
  }
  console.log('available pyPort:', pyPort)

  const env = {
    ...process.env,
  }
  env.PYTHONIOENCODING = 'utf-8'
  env.DEFAULT_PORT = pyPort
  if (app.isPackaged) {
    env.UI_DIST_DIR = path.join(process.resourcesPath, 'react', 'dist')
    env.USER_DATA_DIR = app.getPath('userData')
    env.IS_PACKAGED = '1'
  }

  env.BASE_API_URL =
    process.env.NODE_ENV === 'development' ? 'http://localhost:3000' : 'https://jaaz.app'
  console.log('BASE_API_URL:', env.BASE_API_URL)

  try {
    const proxyEnvVars = await settingsService.getProxyEnvironmentVariables()
    Object.assign(env, proxyEnvVars)
  } catch (error) {
    console.error('Failed to get proxy environment variables:', error)
  }

  const isWindows = process.platform === 'win32'
  // 开发模式优先使用项目虚拟环境，确保后端依赖完整。
  const devVenvPython = isWindows
    ? path.join(appRoot, 'server', '.venv', 'Scripts', 'python.exe')
    : path.join(appRoot, 'server', '.venv', 'bin', 'python')
  const pythonExecutable = app.isPackaged
    ? path.join(process.resourcesPath, 'server', 'dist', 'main', isWindows ? 'main.exe' : 'main')
    : fs.existsSync(devVenvPython) ? devVenvPython : 'python'
  console.log('Python executable exists?', fs.existsSync(pythonExecutable))
  const scriptPath = path.join(__dirname, '../server/main.py')

  pyStartError = null
  pyProc = spawn(
    pythonExecutable,
    app.isPackaged ? ['--port', String(pyPort)] : [scriptPath, '--port', String(pyPort)],
    { env: env }
  )

  pyProc.stdout.on('data', (data) => {
    const log = '[' + new Date().toISOString() + '][PYTHON stdout] ' + data
    logStream.write(log)
    process.stdout.write(log)
  })

  pyProc.stderr.on('data', (data) => {
    const log = '[' + new Date().toISOString() + '][PYTHON stderr] ' + data
    logStream.write(log)
    process.stderr.write(log)
  })

  pyProc.on('error', (err) => {
    pyStartError = err
    const log = '[' + new Date().toISOString() + '][PYTHON spawn error] ' + err.toString() + '\n'
    logStream.write(log)
    process.stderr.write(log)
  })

  pyProc.on('exit', (code, signal) => {
    const log = '[' + new Date().toISOString() + '][PYTHON exited] code=' + code + ', signal=' + signal + '\n'
    logStream.write(log)
  })

  return pyPort
}

const waitForPythonApi = async (port, timeoutMs = 120000) => {
  const deadline = Date.now() + timeoutMs
  let lastError = 'no response'

  while (Date.now() < deadline) {
    if (pyStartError) {
      throw new Error('Failed to launch the Python backend: ' + pyStartError.message)
    }
    if (pyProc && pyProc.exitCode !== null && pyProc.exitCode !== undefined) {
      throw new Error('Python backend exited before becoming ready (code ' + pyProc.exitCode + ').')
    }

    try {
      const response = await fetch('http://127.0.0.1:' + port, {
        signal: AbortSignal.timeout(2000),
      })
      if (response.ok) return
      lastError = 'HTTP ' + response.status
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  throw new Error('Python backend did not become ready within ' + timeoutMs / 1000 + ' seconds (' + lastError + ').')
}

// Add these handlers before app.whenReady()
ipcMain.handle('pick-image', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Images', extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp'] }],
  })

  if (!result.canceled && result.filePaths.length > 0) {
    return result.filePaths
  }
  return null
})

ipcMain.handle('pick-video', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: 'Videos', extensions: ['mp4', 'webm', 'mov', 'avi'] }],
  })

  if (!result.canceled && result.filePaths.length > 0) {
    return result.filePaths[0]
  }
  return null
})

// 已移除上游自动更新逻辑，保留安全空操作以兼容渲染层调用。
ipcMain.handle('check-for-updates', () => {
  return { disabled: true, message: 'Auto-updater is disabled' }
})

ipcMain.handle('restart-and-install', () => {
  return { disabled: true, message: 'Auto-updater is disabled' }
})

const ipcHandlers = require('./ipcHandlers')

for (const [channel, handler] of Object.entries(ipcHandlers)) {
  ipcMain.handle(channel, handler)
}

// Make this app a single instance app
const gotTheLock = app.requestSingleInstanceLock()

if (!gotTheLock) {
  // Another instance is already running, quit this one
  app.quit()
} else {
  // This is the first instance, set up second-instance handler
  app.on('second-instance', (event, commandLine, workingDirectory) => {
    // Someone tried to run a second instance, focus our window instead
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(async () => {
    // Initialize proxy settings for Electron sessions
    try {
      await settingsService.applyProxySettings()
      console.log('Proxy settings applied for Electron sessions')
    } catch (error) {
      console.error('Failed to apply proxy settings for Electron sessions:', error)
    }

    // Start Python API in both development and production
    const pyPort = await startPythonApi()
    await waitForPythonApi(pyPort)
    createWindow(pyPort)
  }).catch((error) => {
    const message = error instanceof Error ? error.message : String(error)
    console.error('Jaaz startup failed:', message)
    dialog.showErrorBox('Jaaz startup failed', message)
    app.quit()
  })
}

// Quit the app and clean up the Python process
app.on('will-quit', async (event) => {
  event.preventDefault()

  try {
    // clear cache
    await session.defaultSession.clearCache()
    console.log('Cache cleared on app exit')
  } catch (error) {
    console.error('Failed to clear cache:', error)
  }

  // kill python process
  if (pyProc) {
    pyProc.kill()
    pyProc = null
  }

  app.exit()
})

app.on('window-all-closed', () => {
  app.quit()
})

// ipcMain.handle("reveal-in-explorer", async (event, filePath) => {
//   try {
//     // Convert relative path to absolute path
//     const fullPath = path.join(app.getPath("userData"), "workspace", filePath);

//     // Use shell.openPath which is the recommended way in Electron
//     await shell.showItemInFolder(fullPath);
//     return { success: true };
//   } catch (error) {
//     console.error("Error revealing file:", error);
//     return { error: error.message };
//   }
// });
