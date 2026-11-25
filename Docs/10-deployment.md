# Jaaz 本地与远端 ComfyUI 部署运行指南

## 1. 环境要求

- 操作系统：Windows 10/11、macOS 或 Linux
- Node.js：20 LTS 及以上
- Python：3.12 或 3.13（服务端位于 `server/.venv`）
- 可选远端或本地 ComfyUI：建议 16GB–24GB 及以上显存，若通过反向代理或 Cloudflare Tunnel 暴露建议使用 HTTPS

## 2. 配置项（`.env` 与 `user_data`）

在仓库根目录创建 `.env`（已被 `.gitignore` 忽略）：

```ini
JAAZ_ACCESS_CODE=请填写不少于16位的强访问码
```

可选环境变量：
- `USER_DATA_DIR`：自定义 SQLite 数据库 `localmanus.db`、配置文件与 `files/` 媒体存储目录。
- `JAAZ_WORKFLOWS_DIR`：自定义 `workflows/` 成对工作流目录（打包只读环境可指向用户可写目录，首次启动自动拷贝内置默认包）。

## 3. 启动步骤（Windows PowerShell）

1. 构建前端静态资源：
   ```powershell
   Push-Location "react"
   npm.cmd install
   npm.cmd run build
   Pop-Location
   ```
2. 启动后端服务（自动托管编译后的前端 SPA 或配合 Vite 开发端口 `5174`）：
   ```powershell
   & "server\.venv\Scripts\python.exe" "server\main.py" --port 57988
   ```
   开发联调时可额外在根目录执行 `npm.cmd run start:frontend`（监听 `http://localhost:5174` 并代理 `/api` 与 `/socket.io` 至 `127.0.0.1:57988`）。

## 4. ComfyUI 工作流接入与维护

- 成对工作流存放于 `workflows/<workflow_name>/workflow.api.json` 与 `jaaz.workflow.json`。
- 命令行快速校验与管理：
  ```powershell
  & "server\.venv\Scripts\python.exe" "server\scripts\workflow_cli.py" list
  & "server\.venv\Scripts\python.exe" "server\scripts\workflow_cli.py" validate "<api.json>" "<jaaz.workflow.json>"
  ```
- 重启后端前，请确认 `jobs` 表无 `status='running'` 任务；若意外中断，重启后 `job_recovery` 会自动轮询远端 `/history` 找回已完成产出。
