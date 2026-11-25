"""程序说明：供外部 AI Agent 与开发者使用的 ComfyUI 工作流解析、校验、安装、启停与导出单文件 CLI 工具。"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from typing import Any, Dict, Optional

# 避免 Windows 控制台非 UTF-8 编码打印报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

with contextlib.redirect_stdout(sys.stderr):
    import asyncio
    from services.comfy_workflow_pack import (
        WORKFLOWS_DIR,
        WorkflowPackValidationError,
        build_export_pack,
        compute_file_sha256,
        save_pack_to_workflows_dir,
        scan_source_workflows_dir,
        summarize_api_json_for_agent,
        update_pack_enabled_flag,
        validate_workflow_pack,
    )
    from services.config_service import USER_DATA_DIR

DEFAULT_DB_PATH = os.path.join(USER_DATA_DIR, "localmanus.db")


def _open_db(db_path: str):
    """按需打开指定路径数据库并将迁移初始化日志定向到 stderr，保证 stdout 纯 JSON 输出。"""
    with contextlib.redirect_stdout(sys.stderr):
        from services.db_service import DatabaseService

        return DatabaseService(db_path=db_path)


def _load_json_file(path: str) -> Any:
    """使用 utf-8-sig 安全读取 JSON 文件。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _fetch_object_info_sync(comfy_url: str) -> Optional[Dict[str, Any]]:
    """可选同步拉取指定 ComfyUI 服务的 /api/object_info 以补全枚举候选项。"""
    base = str(comfy_url or "").strip().rstrip("/")
    if not base:
        return None
    try:
        from utils.http_client import HttpClient

        with HttpClient.create_sync(timeout=5.0) as client:
            for endpoint in ("/api/object_info", "/object_info"):
                resp = client.get(f"{base}{endpoint}")
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, dict):
                        return payload
    except Exception:
        return None
    return None


def _cmd_inspect(args: argparse.Namespace) -> int:
    api_json = _load_json_file(args.api_json)
    object_info = _fetch_object_info_sync(args.comfy_url) if args.comfy_url else None
    summary = summarize_api_json_for_agent(api_json, object_info=object_info)
    summary["used_object_info"] = bool(object_info)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    api_json = _load_json_file(args.api_json)
    cfg_json = _load_json_file(args.config_json)
    res = validate_workflow_pack(api_json, cfg_json)
    if not res["valid"]:
        print(
            json.dumps(
                {"valid": False, "errors": res["errors"]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "name": res["normalized"]["config_json"]["name"],
                "capability": res["normalized"]["config_json"]["capability"],
                "output_kind": res["normalized"]["config_json"]["output_kind"],
                "checksum": res["normalized"]["checksum"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    api_json = _load_json_file(args.api_json)
    cfg_json = _load_json_file(args.config_json)
    if isinstance(cfg_json, dict):
        if args.disabled:
            cfg_json["enabled"] = False
        if args.source_file:
            cfg_json["source_file"] = args.source_file
        if args.source_sha256:
            cfg_json["source_sha256"] = args.source_sha256
        elif args.source_file and not cfg_json.get("source_sha256") and os.path.isfile(args.api_json):
            cfg_json["source_sha256"] = compute_file_sha256(args.api_json)

    saved = save_pack_to_workflows_dir(
        api_json, cfg_json, workflows_dir=args.workflows_dir
    )
    cfg = saved["config_json"]
    db_result: Optional[Dict[str, Any]] = None

    if not args.no_db:
        db = _open_db(args.db_path)
        db_result = db._upsert_comfy_workflow_by_name_sync(
            name=cfg["name"],
            api_json=json.dumps(saved["api_json"], ensure_ascii=False),
            description=cfg["description"],
            inputs=json.dumps(cfg["inputs"], ensure_ascii=False),
            outputs=json.dumps(cfg.get("outputs"), ensure_ascii=False)
            if cfg.get("outputs") is not None
            else None,
            display_name=cfg["display_name"],
            capability=cfg["capability"],
            output_kind=cfg["output_kind"],
            instance_id=cfg["instance_id"] or None,
            source_mode=saved["source_mode"],
            source_path=saved["source_path"],
            seed_strategy=cfg["seed_strategy"],
            schema_version=cfg["schema_version"],
            enabled=1 if cfg["enabled"] else 0,
            checksum=saved["checksum"],
        )

    print(
        json.dumps(
            {
                "success": True,
                "name": cfg["name"],
                "display_name": cfg["display_name"],
                "capability": cfg["capability"],
                "output_kind": cfg["output_kind"],
                "enabled": cfg["enabled"],
                "api_path": saved["api_path"],
                "config_path": saved["config_path"],
                "db": db_result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    db = _open_db(args.db_path)
    rows = db._list_comfy_workflows_sync(enabled_only=False)
    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "display_name": r.get("display_name") or r["name"],
            "capability": r.get("capability") or "t2i",
            "output_kind": r.get("output_kind") or "image",
            "enabled": bool(r.get("enabled", 1)),
            "source_mode": r.get("source_mode") or "db",
            "source_path": r.get("source_path") or "",
        }
        for r in rows
    ]
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def _toggle_enabled(args: argparse.Namespace, enabled: bool) -> int:
    db = _open_db(args.db_path)
    rows = db._list_comfy_workflows_sync(enabled_only=False)
    target = None
    target_key = str(args.name_or_id).strip()
    for row in rows:
        if str(row["id"]) == target_key or str(row["name"]) == target_key:
            target = row
            break
    if target is None:
        print(f"未找到工作流: {target_key}", file=sys.stderr)
        return 1

    updated = db._set_comfy_workflow_enabled_sync(target["id"], enabled)
    if updated and updated.get("source_mode") in ("pack_dir", "pack_pair") and updated.get("source_path"):
        update_pack_enabled_flag(
            str(updated["source_path"]), enabled, workflows_dir=args.workflows_dir
        )

    print(
        json.dumps(
            {
                "id": target["id"],
                "name": target["name"],
                "enabled": enabled,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_export_all(args: argparse.Namespace) -> int:
    db = _open_db(args.db_path)
    rows = db._list_comfy_workflows_sync(enabled_only=False)
    exported: list[dict[str, Any]] = []
    for row in rows:
        if row.get("source_mode") != "db":
            continue
        pack = build_export_pack(row)
        saved = save_pack_to_workflows_dir(
            pack["api_json"], pack["config_json"], workflows_dir=args.workflows_dir
        )
        db._update_comfy_workflow_sync(
            row["id"],
            {
                "source_mode": saved["source_mode"],
                "source_path": saved["source_path"],
                "checksum": saved["checksum"],
            },
        )
        exported.append(
            {
                "id": row["id"],
                "name": row["name"],
                "source_path": saved["source_path"],
            }
        )
    print(json.dumps({"exported": exported}, ensure_ascii=False, indent=2))
    return 0


def _cmd_check_source(args: argparse.Namespace) -> int:
    """扫描 workflows/source/（或指定目录）并输出待导入/已导入/无效文件 JSON 报告。"""
    source_dir = args.source_dir or os.path.join(args.workflows_dir, "source")
    scan = scan_source_workflows_dir(
        source_dir=source_dir, workflows_dir=args.workflows_dir
    )
    print(json.dumps(scan, ensure_ascii=False, indent=2))
    return 0


def _cmd_sync_source(args: argparse.Namespace) -> int:
    """调用内置 LLM 或草稿兜底，自动导入 workflows/source/ 中新增或变更的原始工作流。"""
    source_dir = args.source_dir or os.path.join(args.workflows_dir, "source")
    db = _open_db(args.db_path)
    object_info = _fetch_object_info_sync(args.comfy_url) if args.comfy_url else None
    with contextlib.redirect_stdout(sys.stderr):
        from services.comfy_workflow_ai_importer import auto_import_new_source_workflows

        res = asyncio.run(
            auto_import_new_source_workflows(
                source_dir=source_dir,
                workflows_dir=args.workflows_dir,
                db=db,
                provider=args.provider or "",
                model=args.model or "",
                object_info=object_info,
                fallback_to_draft=bool(args.fallback_draft),
            )
        )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Jaaz ComfyUI 成对工作流 CLI 工具（支持 AI Agent 与命令行一键导入、校验和启停）"
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help="SQLite 数据库路径（默认读取 USER_DATA_DIR/localmanus.db）",
    )
    parser.add_argument(
        "--workflows-dir",
        default=WORKFLOWS_DIR,
        help="项目工作流成对文件目录（默认为 <repo_root>/workflows）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="读取 API JSON 并输出节点摘要与枚举项")
    p_inspect.add_argument("api_json", help="ComfyUI Export (API) JSON 文件路径")
    p_inspect.add_argument("--comfy-url", default="", help="可选 ComfyUI 服务地址用于拉取 /object_info 枚举")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_val = sub.add_parser("validate", help="严格校验 API JSON + jaaz.workflow.json 成对文件")
    p_val.add_argument("api_json", help="API JSON 文件路径")
    p_val.add_argument("config_json", help="jaaz.workflow.json 文件路径")
    p_val.set_defaults(func=_cmd_validate)

    p_inst = sub.add_parser("install", help="校验并将工作流写入 workflows/ 目录和数据库")
    p_inst.add_argument("api_json", help="API JSON 文件路径")
    p_inst.add_argument("config_json", help="jaaz.workflow.json 文件路径")
    p_inst.add_argument("--disabled", action="store_true", help="导入后默认设为停用")
    p_inst.add_argument("--no-db", action="store_true", help="仅写入 workflows/ 目录不立即写库")
    p_inst.add_argument("--source-file", default="", help="可选：记录 workflows/source/ 原始文件名")
    p_inst.add_argument("--source-sha256", default="", help="可选：记录原始源文件 SHA-256")
    p_inst.set_defaults(func=_cmd_install)

    p_list = sub.add_parser("list", help="列出数据库中的全部工作流及启停状态")
    p_list.set_defaults(func=_cmd_list)

    p_en = sub.add_parser("enable", help="启用指定名称或 ID 的工作流")
    p_en.add_argument("name_or_id", help="工作流 name 或 id")
    p_en.set_defaults(func=lambda a: _toggle_enabled(a, True))

    p_dis = sub.add_parser("disable", help="停用指定名称或 ID 的工作流（Agent 将不再选用）")
    p_dis.add_argument("name_or_id", help="工作流 name 或 id")
    p_dis.set_defaults(func=lambda a: _toggle_enabled(a, False))

    p_exp = sub.add_parser("export-all", help="将所有仅存于 DB 的历史工作流导出为标准 workflows/<name>/ 文件对")
    p_exp.set_defaults(func=_cmd_export_all)

    p_chk = sub.add_parser("check-source", help="扫描 workflows/source/ 中新增、已导入或异常的原始工作流文件")
    p_chk.add_argument("--source-dir", default="", help="可选原始工作流目录，默认为 <workflows_dir>/source")
    p_chk.set_defaults(func=_cmd_check_source)

    p_sync = sub.add_parser("sync-source", help="自动检测并导入 workflows/source/ 中新增的原始工作流")
    p_sync.add_argument("--source-dir", default="", help="可选原始工作流目录，默认为 <workflows_dir>/source")
    p_sync.add_argument("--comfy-url", default="", help="可选 ComfyUI 服务地址用于拉取 /object_info 枚举")
    p_sync.add_argument("--provider", default="", help="可选文本大模型提供商")
    p_sync.add_argument("--model", default="", help="可选文本大模型名称")
    p_sync.add_argument("--fallback-draft", action="store_true", help="无可用 LLM 时退回生成停用状态草稿")
    p_sync.set_defaults(func=_cmd_sync_source)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except WorkflowPackValidationError as exc:
        print(f"校验失败: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
