"""程序说明：提供工作区文件操作与受控本机媒体浏览接口，所有路径操作均做边界校验。"""
import mimetypes
import os
import platform
import subprocess
import traceback
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from services.config_service import USER_DATA_DIR
from utils.path_security import (
    PathSecurityError,
    ensure_path_in_allowed_roots,
    get_allowed_browse_roots,
    is_path_in_allowed_roots,
    safe_join,
)

router = APIRouter(prefix="/api")

WORKSPACE_ROOT = os.path.join(USER_DATA_DIR, "workspace")


def _safe_workspace_path(rel_path: str, *, allow_root: bool = False) -> str:
    """将工作区相对路径安全解析到 WORKSPACE_ROOT 内，越界抛出 403。"""
    if allow_root and isinstance(rel_path, str) and not rel_path.strip():
        rel_path = "."
    try:
        resolved = safe_join(WORKSPACE_ROOT, rel_path)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not allow_root and resolved == os.path.realpath(WORKSPACE_ROOT):
        raise HTTPException(status_code=403, detail="Operation on workspace root is not allowed")
    return resolved


def _ensure_allowed_browse_path(target_path: str) -> tuple[str, list[str]]:
    """校验本机浏览/预览路径落在允许根目录白名单内，越界抛出 403。"""
    allowed_roots = get_allowed_browse_roots()
    try:
        resolved = ensure_path_in_allowed_roots(target_path, allowed_roots)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return resolved, allowed_roots


@router.post("/update_file")
async def update_file(request: Request):
    path = ""
    try:
        data = await request.json()
        path = data.get("path", "")
        content = data.get("content")
        if not isinstance(path, str) or content is None:
            raise HTTPException(status_code=400, detail="Missing 'path' or 'content'")

        full_path = _safe_workspace_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(str(content))
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e), "path": path}


@router.post("/create_file")
async def create_file(request: Request):
    try:
        data = await request.json()
        rel_dir = data.get("rel_dir", "")
        target_dir = _safe_workspace_path(rel_dir, allow_root=True)
        path = os.path.join(target_dir, "Untitled.md")
        dir_name, base_name = os.path.split(path)
        name, ext = os.path.splitext(base_name)

        candidate_path = path
        counter = 1
        while os.path.exists(candidate_path):
            new_base = f"{name} {counter}{ext}"
            candidate_path = os.path.join(dir_name, new_base)
            counter += 1

        os.makedirs(os.path.dirname(candidate_path), exist_ok=True)
        with open(candidate_path, "w", encoding="utf-8") as f:
            f.write("")
        return {"path": os.path.relpath(candidate_path, os.path.realpath(WORKSPACE_ROOT))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_file")
async def delete_file(request: Request):
    try:
        data = await request.json()
        path = data.get("path")
        if not isinstance(path, str) or not path.strip():
            raise HTTPException(status_code=400, detail="Missing file path")

        full_path = _safe_workspace_path(path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        if os.path.isdir(full_path):
            raise HTTPException(status_code=400, detail="Path is a directory")

        os.remove(full_path)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rename_file")
async def rename_file(request: Request):
    try:
        data = await request.json()
        old_rel = data.get("old_path")
        new_title = data.get("new_title")
        if not isinstance(old_rel, str) or not isinstance(new_title, str) or not new_title.strip():
            raise HTTPException(status_code=400, detail="Missing 'old_path' or 'new_title'")

        if "/" in new_title or "\\" in new_title or ".." in new_title or "\x00" in new_title:
            raise HTTPException(status_code=403, detail="Invalid target filename")

        old_path = _safe_workspace_path(old_rel)
        if not os.path.exists(old_path):
            return {"error": f"File {old_rel} does not exist", "path": old_rel}

        workspace_real = os.path.realpath(WORKSPACE_ROOT)
        rel_parent = os.path.relpath(os.path.dirname(old_path), workspace_real)
        new_rel = new_title if rel_parent == "." else os.path.join(rel_parent, new_title)
        new_path = _safe_workspace_path(new_rel)
        os.rename(old_path, new_path)
        return {"success": True, "path": os.path.relpath(new_path, workspace_real)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


@router.post("/read_file")
async def read_file(request: Request):
    path = ""
    try:
        data = await request.json()
        path = data.get("path", "")
        if not isinstance(path, str) or not path.strip():
            raise HTTPException(status_code=400, detail="Missing file path")

        full_path = _safe_workspace_path(path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                return {"content": content}
        return {"error": f"File {path} does not exist", "path": path}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e), "path": path}


@router.get("/list_files_in_dir")
async def list_files_in_dir(rel_path: str = ""):
    try:
        full_path = _safe_workspace_path(rel_path, allow_root=True)
        files = os.listdir(full_path)
        file_nodes = []
        for file in files:
            file_path = os.path.join(full_path, file)
            file_nodes.append({
                "name": file,
                "is_dir": os.path.isdir(file_path),
                "rel_path": os.path.join(rel_path, file) if rel_path else file,
                "mtime": os.path.getmtime(file_path),
            })
        file_nodes.sort(key=lambda x: x["mtime"], reverse=True)
        for node in file_nodes:
            node.pop("mtime")
        return file_nodes
    except HTTPException:
        raise
    except Exception:
        return []


@router.post("/open_folder_in_explorer")
async def open_folder_in_explorer(request: Request):
    """在系统文件管理器中打开允许目录内的指定文件夹。"""
    try:
        data = await request.json()
        folder_path = data.get("path")

        if not folder_path:
            raise HTTPException(status_code=400, detail="Missing folder path")

        resolved_path, _ = _ensure_allowed_browse_path(folder_path)
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="Folder not found")
        if not os.path.isdir(resolved_path):
            raise HTTPException(status_code=400, detail="Path is not a directory")

        system = platform.system()
        if system == "Windows":
            subprocess.run(["explorer", resolved_path], check=True)
        elif system == "Darwin":
            subprocess.run(["open", resolved_path], check=True)
        elif system == "Linux":
            subprocess.run(["xdg-open", resolved_path], check=True)
        else:
            raise HTTPException(status_code=500, detail=f"Unsupported operating system: {system}")

        return {"success": True, "message": "Folder opened in system explorer"}
    except HTTPException:
        raise
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to open folder: {str(e)}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error opening folder: {str(e)}")


@router.get("/browse_filesystem")
async def browse_filesystem(path: str = ""):
    """浏览允许根目录白名单内的文件夹和文件。"""
    try:
        allowed_roots = get_allowed_browse_roots()
        if not path:
            home_dir = os.path.realpath(os.path.expanduser("~"))
            path = home_dir if is_path_in_allowed_roots(home_dir, allowed_roots) else allowed_roots[0]

        resolved_path, allowed_roots = _ensure_allowed_browse_path(path)
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="Path not found")
        if not os.path.isdir(resolved_path):
            raise HTTPException(status_code=400, detail="Path is not a directory")

        items = []
        try:
            for item in os.listdir(resolved_path):
                item_path = os.path.join(resolved_path, item)
                if item.startswith("."):
                    continue
                try:
                    stat = os.stat(item_path)
                    is_dir = os.path.isdir(item_path)
                    file_type = "folder" if is_dir else get_file_type(item_path)
                    size = stat.st_size if not is_dir else None
                    is_media = file_type in ["image", "video"]
                    items.append({
                        "name": item,
                        "path": item_path,
                        "type": file_type,
                        "size": size,
                        "mtime": stat.st_mtime,
                        "is_directory": is_dir,
                        "is_media": is_media,
                        "has_thumbnail": is_media,
                    })
                except (OSError, PermissionError):
                    continue
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        items.sort(key=lambda x: (not x["is_directory"], x["name"].lower()))
        parent_candidate = os.path.dirname(resolved_path)
        parent_path = (
            parent_candidate
            if parent_candidate != resolved_path and is_path_in_allowed_roots(parent_candidate, allowed_roots)
            else None
        )

        return {
            "current_path": resolved_path,
            "parent_path": parent_path,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_media_files")
async def get_media_files(path: str):
    """获取允许目录内的图片和视频文件列表。"""
    try:
        resolved_path, _ = _ensure_allowed_browse_path(path)
        if not os.path.exists(resolved_path) or not os.path.isdir(resolved_path):
            raise HTTPException(status_code=400, detail="Invalid directory path")

        media_files = []
        try:
            for item in os.listdir(resolved_path):
                item_path = os.path.join(resolved_path, item)
                if os.path.isfile(item_path):
                    file_type = get_file_type(item_path)
                    if file_type in ["image", "video"]:
                        stat = os.stat(item_path)
                        media_files.append({
                            "name": item,
                            "path": item_path,
                            "type": file_type,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        })
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        media_files.sort(key=lambda x: x["mtime"], reverse=True)
        return media_files
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_file_thumbnail")
async def get_file_thumbnail(file_path: str):
    """获取允许目录内文件的缩略图元信息。"""
    try:
        resolved_path, _ = _ensure_allowed_browse_path(file_path)
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="File not found")

        file_type = get_file_type(resolved_path)
        return {
            "path": resolved_path,
            "type": file_type,
            "exists": True,
            "can_preview": file_type in ["image", "video"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_file_type(file_path: str) -> str:
    """根据文件扩展名判断文件类型。"""
    if os.path.isdir(file_path):
        return "folder"

    _, ext = os.path.splitext(file_path.lower())

    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg", ".ico"}
    video_extensions = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"}
    audio_extensions = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"}
    document_extensions = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".pages"}
    archive_extensions = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}
    code_extensions = {".py", ".js", ".html", ".css", ".java", ".cpp", ".c", ".php", ".rb", ".go", ".rs"}

    if ext in image_extensions:
        return "image"
    if ext in video_extensions:
        return "video"
    if ext in audio_extensions:
        return "audio"
    if ext in document_extensions:
        return "document"
    if ext in archive_extensions:
        return "archive"
    if ext in code_extensions:
        return "code"
    return "file"


@router.get("/serve_file")
async def serve_file(file_path: str):
    """提供允许目录内的图片和视频文件预览。"""
    try:
        resolved_path, _ = _ensure_allowed_browse_path(file_path)
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="File not found")
        if not os.path.isfile(resolved_path):
            raise HTTPException(status_code=400, detail="Path is not a file")

        file_type = get_file_type(resolved_path)
        if file_type not in ["image", "video"]:
            raise HTTPException(status_code=400, detail="File type not supported for preview")

        mime_type, _ = mimetypes.guess_type(resolved_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        return FileResponse(
            resolved_path,
            media_type=mime_type,
            filename=os.path.basename(resolved_path),
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_file_info")
async def get_file_info(file_path: str):
    """获取允许目录内文件的详细信息。"""
    try:
        resolved_path, _ = _ensure_allowed_browse_path(file_path)
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="File not found")

        stat = os.stat(resolved_path)
        file_type = get_file_type(resolved_path)

        return {
            "name": os.path.basename(resolved_path),
            "path": resolved_path,
            "type": file_type,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "ctime": stat.st_ctime,
            "is_directory": os.path.isdir(resolved_path),
            "is_media": file_type in ["image", "video"],
            "mime_type": mimetypes.guess_type(resolved_path)[0] or "application/octet-stream",
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
