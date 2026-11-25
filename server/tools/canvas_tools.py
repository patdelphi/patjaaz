"""程序说明：提供智能体原生画布排版、分镜框与脚本卡创建、媒体网格重排、流转箭头连线及序号角标标注工具（A2）。"""
from __future__ import annotations

import json
import random
import time
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool

from services.db_service import db_service
from services.websocket_service import broadcast_session_update
from utils.canvas import find_next_best_element_position
from utils.canvas_lock import canvas_lock_manager


def _now_ms() -> int:
    return int(time.time() * 1000)


def _rand_seed() -> int:
    return random.randint(100000, 2147000000)


def _make_base_shape(
    elem_id: str,
    etype: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    stroke_color: str = "#334155",
    bg_color: str = "transparent",
    stroke_width: int = 2,
    stroke_style: str = "solid",
    roundness: Optional[Dict[str, Any]] = None,
    frame_id: Optional[str] = None,
    group_ids: Optional[List[str]] = None,
    custom_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造标准 Excalidraw 几何图形字典。"""
    elem: Dict[str, Any] = {
        "id": elem_id,
        "type": etype,
        "x": round(float(x), 1),
        "y": round(float(y), 1),
        "width": round(float(w), 1),
        "height": round(float(h), 1),
        "angle": 0,
        "strokeColor": stroke_color,
        "backgroundColor": bg_color,
        "fillStyle": "solid",
        "strokeWidth": stroke_width,
        "strokeStyle": stroke_style,
        "roughness": 0,
        "opacity": 100,
        "groupIds": list(group_ids or []),
        "frameId": frame_id,
        "roundness": roundness,
        "seed": _rand_seed(),
        "version": 2,
        "versionNonce": _rand_seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": _now_ms(),
        "link": None,
        "locked": False,
    }
    if custom_data is not None:
        elem["customData"] = custom_data
    return elem


def _make_bound_card(
    card_id: str,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    shape_type: str = "rectangle",
    stroke_color: str = "#2563eb",
    bg_color: str = "#eff6ff",
    text_color: str = "#0f172a",
    font_size: int = 16,
    text_align: str = "left",
    frame_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """创建带内部绑定文字的卡片或菱形决策框。"""
    text_id = f"{card_id}_txt"
    roundness = {"type": 3} if shape_type == "rectangle" else None
    card = _make_base_shape(
        card_id,
        shape_type,
        x,
        y,
        w,
        h,
        stroke_color=stroke_color,
        bg_color=bg_color,
        roundness=roundness,
        frame_id=frame_id,
    )
    card["boundElements"] = [{"id": text_id, "type": "text"}]

    lines = str(text or "").split("\n")
    pad_x = 20.0 if shape_type == "rectangle" else w * 0.22
    pad_y = 14.0 if shape_type == "rectangle" else h * 0.24
    tw = max(40.0, w - pad_x * 2)
    th = min(max(24.0, h - pad_y * 2), max(1, len(lines)) * font_size * 1.25 + 6)
    tx = x + (w - tw) / 2 if text_align == "center" else x + pad_x
    ty = y + (h - th) / 2

    txt_elem = _make_base_shape(
        text_id,
        "text",
        tx,
        ty,
        tw,
        th,
        stroke_color=text_color,
        bg_color="transparent",
        stroke_width=1,
        frame_id=frame_id,
    )
    txt_elem.update(
        {
            "text": text,
            "originalText": text,
            "fontSize": font_size,
            "fontFamily": 2,
            "textAlign": text_align,
            "verticalAlign": "middle",
            "containerId": card_id,
            "lineHeight": 1.25,
            "autoResize": True,
        }
    )
    return [card, txt_elem]


def _resolve_element_by_ref(
    elements: List[Dict[str, Any]],
    files_map: Dict[str, Any],
    ref: str,
) -> Optional[Dict[str, Any]]:
    """支持通过元素 ID、画布媒体真实文件名（如 abc.png / xyz.mp4）或画框/卡片文字片段匹配目标元素。"""
    key = str(ref or "").strip()
    if not key:
        return None
    active = [e for e in elements if isinstance(e, dict) and not e.get("isDeleted")]
    for el in active:
        if str(el.get("id") or "") == key:
            return el

    # 匹配媒体文件名
    clean_fname = key.split("/api/file/", 1)[1] if "/api/file/" in key else key
    for el in active:
        if el.get("type") not in ("image", "video", "audio", "embeddable"):
            continue
        fid = str(el.get("fileId") or el.get("id") or "")
        fentry = files_map.get(fid) if isinstance(files_map, dict) else None
        durl = str((fentry or {}).get("dataURL") or el.get("link") or "")
        if durl.endswith(f"/{clean_fname}") or durl == clean_fname:
            return el

    # 匹配 Frame 名称或绑定文字内容
    by_id = {str(e.get("id")): e for e in active if e.get("id")}
    for el in active:
        if el.get("type") == "frame" and key in str(el.get("name") or ""):
            return el
    for el in active:
        if el.get("type") == "text" and key in str(el.get("text") or ""):
            cid = str(el.get("containerId") or "")
            return by_id.get(cid, el) if cid else el
    return None


def _next_callout_num(elements: List[Dict[str, Any]]) -> int:
    max_n = 0
    for el in elements:
        if not isinstance(el, dict) or el.get("isDeleted"):
            continue
        cd = el.get("customData")
        if isinstance(cd, dict) and cd.get("jaazType") == "callout-badge":
            try:
                n = int(cd.get("calloutNumber") or 0)
                if n > max_n:
                    max_n = n
            except (TypeError, ValueError):
                pass
    return max_n + 1


@tool("canvas_arrange_elements")
async def canvas_arrange_elements_tool(
    action: Literal["create_frame", "create_card", "move_resize", "grid_layout"],
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId],
    title_or_text: str = "",
    target_ref: str = "",
    target_refs: Optional[List[str]] = None,
    frame_ref: str = "",
    shape_type: Literal["rectangle", "diamond"] = "rectangle",
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    columns: int = 2,
    stroke_color: str = "#2563eb",
    bg_color: str = "#eff6ff",
) -> str:
    """Create frames/cards/decision nodes or move, resize, and grid-arrange media/elements directly on the Excalidraw canvas.
    - create_frame: Creates a named stage Frame (`title_or_text`, optional `x`, `y`, `width`, `height`).
    - create_card: Creates a text script box or decision diamond (`title_or_text`, `shape_type`, optional `frame_ref`, `x`, `y`, `width`, `height`).
    - move_resize: Moves/resizes an existing element/image/video (`target_ref` can be element id, filename like `abc.png`, or title) to (`x`, `y`, `width`, `height`) and optional `frame_ref`.
    - grid_layout: Arranges `target_refs` (list of filenames or element ids) into a neat non-overlapping `columns`-column grid inside `frame_ref` or starting at (`x`, `y`).
    """
    ctx = config.get("configurable", {})
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    if not canvas_id:
        return "canvas operation skipped: missing canvas_id"

    touched_elements: List[Dict[str, Any]] = []
    summary_msg = ""

    async with canvas_lock_manager.lock_canvas(canvas_id):
        canvas = await db_service.get_canvas_data(canvas_id)
        data = (canvas or {}).get("data") or {}
        elements: List[Dict[str, Any]] = data.setdefault("elements", [])
        files_map: Dict[str, Any] = data.setdefault("files", {})

        frame_elem = _resolve_element_by_ref(elements, files_map, frame_ref) if frame_ref else None
        resolved_frame_id = str(frame_elem["id"]) if frame_elem and frame_elem.get("type") == "frame" else None

        if action == "create_frame":
            fw = float(width or 820)
            fh = float(height or 1200)
            if x is None or y is None:
                nx, ny = await find_next_best_element_position(data, int(fw), int(fh))
                fx = float(x if x is not None else nx)
                fy = float(y if y is not None else ny)
            else:
                fx, fy = float(x), float(y)
            fid = f"frame_{int(time.time() * 1000) % 1000000}_{random.randint(100, 999)}"
            frame_obj = _make_base_shape(
                fid,
                "frame",
                fx,
                fy,
                fw,
                fh,
                stroke_color="#94a3b8",
                bg_color="transparent",
            )
            frame_obj["name"] = title_or_text or "分镜泳道"
            elements.append(frame_obj)
            touched_elements.append(frame_obj)
            summary_msg = f"Created frame '{frame_obj['name']}' (id={fid}) at ({fx}, {fy}, {fw}x{fh})."

        elif action == "create_card":
            cw = float(width or (460 if shape_type == "diamond" else 560))
            ch = float(height or (240 if shape_type == "diamond" else 220))
            if x is not None and y is not None:
                cx, cy = float(x), float(y)
            elif frame_elem is not None:
                cx = float(frame_elem["x"]) + 36
                cy = float(frame_elem["y"]) + 48
            else:
                nx, ny = await find_next_best_element_position(data, int(cw), int(ch))
                cx, cy = float(nx), float(ny)
            cid = f"card_{int(time.time() * 1000) % 1000000}_{random.randint(100, 999)}"
            align = "center" if shape_type == "diamond" else "left"
            pair = _make_bound_card(
                cid,
                cx,
                cy,
                cw,
                ch,
                title_or_text or "分镜说明",
                shape_type=shape_type,
                stroke_color=stroke_color,
                bg_color=bg_color,
                text_align=align,
                frame_id=resolved_frame_id,
            )
            elements.extend(pair)
            touched_elements.extend(pair)
            summary_msg = f"Created {shape_type} card (id={cid}) at ({cx}, {cy})."

        elif action == "move_resize":
            target = _resolve_element_by_ref(elements, files_map, target_ref)
            if target is None:
                return f"Target element not found for ref='{target_ref}'"
            dx = float(x) - float(target.get("x") or 0) if x is not None else 0.0
            dy = float(y) - float(target.get("y") or 0) if y is not None else 0.0
            if x is not None:
                target["x"] = round(float(x), 1)
            if y is not None:
                target["y"] = round(float(y), 1)
            if width is not None and width > 0:
                target["width"] = round(float(width), 1)
            if height is not None and height > 0:
                target["height"] = round(float(height), 1)
            if resolved_frame_id is not None:
                target["frameId"] = resolved_frame_id
            target["version"] = int(target.get("version") or 1) + 1
            target["versionNonce"] = _rand_seed()
            target["updated"] = _now_ms()
            touched_elements.append(target)

            # 同步平移容器内部绑定文字
            for bound in target.get("boundElements") or []:
                if isinstance(bound, dict) and bound.get("type") == "text":
                    bt = _resolve_element_by_ref(elements, files_map, str(bound.get("id") or ""))
                    if bt is not None:
                        bt["x"] = round(float(bt.get("x") or 0) + dx, 1)
                        bt["y"] = round(float(bt.get("y") or 0) + dy, 1)
                        bt["version"] = int(bt.get("version") or 1) + 1
                        bt["versionNonce"] = _rand_seed()
                        bt["updated"] = _now_ms()
                        touched_elements.append(bt)

            summary_msg = f"Moved/resized element '{target['id']}' to ({target['x']}, {target['y']}, {target['width']}x{target['height']})."

        elif action == "grid_layout":
            refs = list(target_refs or ([] if not target_ref else [target_ref]))
            cols = max(1, int(columns or 2))
            cell_w = float(width or 560)
            gap = 40.0
            start_x = float(x if x is not None else ((frame_elem["x"] + 40) if frame_elem else 120))
            start_y = float(y if y is not None else ((frame_elem["y"] + 80) if frame_elem else 120))
            cur_row_y = start_y
            row_max_h = 0.0
            placed_count = 0

            for idx, r in enumerate(refs):
                el = _resolve_element_by_ref(elements, files_map, r)
                if el is None:
                    continue
                col_i = placed_count % cols
                if placed_count > 0 and col_i == 0:
                    cur_row_y += row_max_h + gap
                    row_max_h = 0.0
                orig_w = max(1.0, float(el.get("width") or cell_w))
                orig_h = max(1.0, float(el.get("height") or cell_w))
                scale = cell_w / orig_w
                new_h = round(orig_h * scale, 1)
                el["x"] = round(start_x + col_i * (cell_w + gap), 1)
                el["y"] = round(cur_row_y, 1)
                el["width"] = round(cell_w, 1)
                el["height"] = new_h
                if resolved_frame_id is not None:
                    el["frameId"] = resolved_frame_id
                el["version"] = int(el.get("version") or 1) + 1
                el["versionNonce"] = _rand_seed()
                el["updated"] = _now_ms()
                row_max_h = max(row_max_h, new_h)
                touched_elements.append(el)
                placed_count += 1

            summary_msg = f"Arranged {placed_count} elements in a {cols}-column grid starting at ({start_x}, {start_y})."

        await db_service.save_canvas_data(canvas_id, json.dumps(data))

    if touched_elements:
        await broadcast_session_update(
            session_id,
            canvas_id,
            {
                "type": "canvas_elements_updated",
                "canvas_id": canvas_id,
                "elements": touched_elements,
            },
        )
    return summary_msg


@tool("canvas_connect_and_badge")
async def canvas_connect_and_badge_tool(
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId],
    source_ref: str = "",
    target_ref: str = "",
    arrow_label: str = "",
    badge_target_ref: str = "",
    badge_number: Optional[int] = None,
    badge_rel_x: float = 0.04,
    badge_rel_y: float = 0.04,
    stroke_color: str = "#2563eb",
    badge_color: str = "#ef4444",
) -> str:
    """Draw a labeled directional flow arrow connecting `source_ref` -> `target_ref` on the canvas, and/or place a numbered callout badge (`①`, `②`, ...) on `badge_target_ref` at normalized position (`badge_rel_x`, `badge_rel_y` in 0.0~1.0).
    References (`source_ref`, `target_ref`, `badge_target_ref`) accept element IDs, media filenames (e.g. `abc.png` / `vid.mp4`), or card text snippets.
    """
    ctx = config.get("configurable", {})
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    if not canvas_id:
        return "canvas annotation skipped: missing canvas_id"

    touched_elements: List[Dict[str, Any]] = []
    notes: List[str] = []

    async with canvas_lock_manager.lock_canvas(canvas_id):
        canvas = await db_service.get_canvas_data(canvas_id)
        data = (canvas or {}).get("data") or {}
        elements: List[Dict[str, Any]] = data.setdefault("elements", [])
        files_map: Dict[str, Any] = data.setdefault("files", {})

        if source_ref and target_ref:
            src = _resolve_element_by_ref(elements, files_map, source_ref)
            dst = _resolve_element_by_ref(elements, files_map, target_ref)
            if src is None or dst is None:
                return f"Could not resolve source_ref='{source_ref}' or target_ref='{target_ref}'"

            sx = float(src["x"]) + float(src["width"])
            sy = float(src["y"]) + float(src["height"]) / 2
            dx = float(dst["x"])
            dy = float(dst["y"]) + float(dst["height"]) / 2
            if dx < sx - 20:
                # 上下流转连线
                sx = float(src["x"]) + float(src["width"]) / 2
                sy = float(src["y"]) + float(src["height"])
                dx = float(dst["x"]) + float(dst["width"]) / 2
                dy = float(dst["y"])
                pts_abs: List[Tuple[float, float]] = [(sx, sy), (dx, dy)]
            else:
                mid_x = round((sx + dx) / 2, 1)
                pts_abs = [(sx, sy), (mid_x, sy), (mid_x, dy), (dx, dy)]

            x0, y0 = pts_abs[0]
            rel_pts = [[round(px - x0, 1), round(py - y0, 1)] for px, py in pts_abs]
            xs = [p[0] for p in rel_pts]
            ys = [p[1] for p in rel_pts]
            aid = f"arrow_{int(time.time() * 1000) % 1000000}_{random.randint(100, 999)}"
            arrow = _make_base_shape(
                aid,
                "arrow",
                x0,
                y0,
                max(1.0, max(xs) - min(xs)),
                max(1.0, max(ys) - min(ys)),
                stroke_color=stroke_color,
                stroke_width=3,
                roundness={"type": 2},
            )
            arrow.update(
                {
                    "points": rel_pts,
                    "lastCommittedPoint": None,
                    "startBinding": {"elementId": src["id"], "focus": 0, "gap": 8},
                    "endBinding": {"elementId": dst["id"], "focus": 0, "gap": 8},
                    "startArrowhead": None,
                    "endArrowhead": "arrow",
                }
            )
            for endpoint in (src, dst):
                be = endpoint.setdefault("boundElements", [])
                if not isinstance(be, list):
                    be = []
                    endpoint["boundElements"] = be
                be.append({"id": aid, "type": "arrow"})
                endpoint["version"] = int(endpoint.get("version") or 1) + 1
                endpoint["versionNonce"] = _rand_seed()
                endpoint["updated"] = _now_ms()
                touched_elements.append(endpoint)

            elements.append(arrow)
            touched_elements.append(arrow)

            if arrow_label.strip():
                mx = (pts_abs[0][0] + pts_abs[-1][0]) / 2
                my = (pts_abs[0][1] + pts_abs[-1][1]) / 2 - 26
                pw = max(140.0, min(280.0, len(arrow_label) * 14 + 28))
                ph = 38.0
                pill = _make_bound_card(
                    f"{aid}_lbl",
                    mx - pw / 2,
                    my - ph / 2,
                    pw,
                    ph,
                    arrow_label.strip(),
                    stroke_color=stroke_color,
                    bg_color="#ffffff",
                    text_color=stroke_color,
                    font_size=13,
                    text_align="center",
                )
                elements.extend(pill)
                touched_elements.extend(pill)
            notes.append(f"Connected '{src['id']}' -> '{dst['id']}' with arrow '{aid}'.")

        if badge_target_ref:
            btarget = _resolve_element_by_ref(elements, files_map, badge_target_ref)
            if btarget is None:
                return f"Badge target not found for ref='{badge_target_ref}'"
            num = int(badge_number) if badge_number is not None else _next_callout_num(elements)
            rx = max(0.0, min(1.0, float(badge_rel_x)))
            ry = max(0.0, min(1.0, float(badge_rel_y)))
            cx = float(btarget["x"]) + float(btarget["width"]) * rx
            cy = float(btarget["y"]) + float(btarget["height"]) * ry
            diameter = 38.0
            grp_id = f"callout_grp_{int(time.time() * 1000) % 1000000}_{num}"
            circle = _make_base_shape(
                f"badge_c_{grp_id}",
                "ellipse",
                cx - diameter / 2,
                cy - diameter / 2,
                diameter,
                diameter,
                stroke_color="#ffffff",
                bg_color=badge_color,
                stroke_width=2,
                group_ids=[grp_id],
                custom_data={
                    "jaazType": "callout-badge",
                    "calloutNumber": num,
                    "targetElementId": str(btarget["id"]),
                },
            )
            label_str = str(num)
            fs = 18 if len(label_str) == 1 else 16
            tw = len(label_str) * fs * 0.6
            th = fs * 1.25
            txt = _make_base_shape(
                f"badge_t_{grp_id}",
                "text",
                cx - tw / 2,
                cy - th / 2,
                tw,
                th,
                stroke_color="#ffffff",
                stroke_width=1,
                group_ids=[grp_id],
                custom_data={"jaazType": "callout-badge-label", "calloutNumber": num},
            )
            txt.update(
                {
                    "text": label_str,
                    "originalText": label_str,
                    "fontSize": fs,
                    "fontFamily": 2,
                    "textAlign": "center",
                    "verticalAlign": "middle",
                    "containerId": None,
                    "lineHeight": 1.25,
                    "autoResize": True,
                }
            )
            elements.extend([circle, txt])
            touched_elements.extend([circle, txt])
            notes.append(f"Placed callout badge #{num} on '{btarget['id']}'.")

        if touched_elements:
            await db_service.save_canvas_data(canvas_id, json.dumps(data))

    if touched_elements:
        await broadcast_session_update(
            session_id,
            canvas_id,
            {
                "type": "canvas_elements_updated",
                "canvas_id": canvas_id,
                "elements": touched_elements,
            },
        )
    return " ".join(notes) if notes else "No canvas changes requested."
