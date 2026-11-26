"""程序说明：将多行剧本大纲或结构化镜头列表自动拆解并原子铺排为无限画布故事板矩阵（含角色设定框、分镜泳道、脚本卡、闭合块箭头与序号角标，P8-1）。"""
from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, List, Optional

from services.db_service import DatabaseService, db_service
from services.websocket_service import broadcast_session_update
from tools.canvas_tools import _make_base_shape, _make_bound_card, _next_callout_num
from utils.canvas import find_next_best_element_position
from utils.canvas_lock import canvas_lock_manager

_QUOTE_RE = re.compile(r'[“"「]([^”"」]{1,80})[”"」]')


def _make_block_arrow_element(
    elem_id: str,
    x: float,
    y: float,
    width: float = 84.0,
    height: float = 42.0,
    fill_color: str = "#dbeafe",
    stroke_color: str = "#2563eb",
) -> Dict[str, Any]:
    """构造与前端 createBlockArrowElement 顶点契约一致的闭合多边形块箭头元素。"""
    head_len = round(min(width * 0.42, height * 0.95), 1)
    shaft_x = round(width - head_len, 1)
    tail_half = round(height * 0.24, 1)
    cy = round(height / 2.0, 1)
    pts = [
        [0.0, round(cy - tail_half, 1)],
        [shaft_x, round(cy - tail_half, 1)],
        [shaft_x, 0.0],
        [round(width, 1), cy],
        [shaft_x, round(height, 1)],
        [shaft_x, round(cy + tail_half, 1)],
        [0.0, round(cy + tail_half, 1)],
        [0.0, round(cy - tail_half, 1)],
    ]
    el = _make_base_shape(
        elem_id,
        "line",
        x,
        y,
        width,
        height,
        stroke_color=stroke_color,
        bg_color=fill_color,
        stroke_width=2,
        custom_data={
            "kind": "block-arrow",
            "direction": "right",
            "headRatio": 0.42,
            "tailRatio": 0.48,
        },
    )
    el.update({"points": pts, "lastCommittedPoint": pts[-1]})
    return el


def parse_raw_script_into_shots(
    raw_script: str,
    default_shot_duration_sec: float = 15.0,
    max_shots: int = 12,
) -> List[Dict[str, Any]]:
    """将多行剧本或分幕文本解析为结构化镜头列表，自动提取引号内对白作为字幕。"""
    lines = [
        re.sub(r"^\s*(?:第\s*\d+\s*[镜幕场]|shot\s*\d+|\d+[.、:：))\s])\s*", "", ln, flags=re.IGNORECASE).strip()
        for ln in str(raw_script or "").splitlines()
        if ln.strip()
    ]
    shots: List[Dict[str, Any]] = []
    dur = max(3.0, round(float(default_shot_duration_sec or 15.0), 1))
    for idx, line in enumerate(lines[:max_shots], 1):
        quotes = _QUOTE_RE.findall(line)
        dialogue = quotes[0].strip() if quotes else ""
        shots.append(
            {
                "index": idx,
                "title": f"第 {idx} 镜",
                "visual": line,
                "camera": "电影级平稳推拉运镜",
                "dialogue": dialogue,
                "sfx": "自然环境同期声与空间混响",
                "duration_sec": dur,
            }
        )
    return shots


async def plan_and_layout_storyboard_on_canvas(
    canvas_id: str,
    *,
    film_title: str = "短片分镜企划",
    character_anchor_desc: str = "",
    raw_script: str = "",
    shots: Optional[List[Dict[str, Any]]] = None,
    shot_duration_sec: float = 15.0,
    session_id: str = "",
    db: Optional[DatabaseService] = None,
) -> Dict[str, Any]:
    """在指定画布防碰撞位置自动铺排角色设定画框与横向分镜泳道矩阵，并广播实时场景更新。"""
    if not canvas_id:
        raise ValueError("canvas_id 不能为空")

    active_db = db or db_service
    normalized_shots: List[Dict[str, Any]] = []
    if shots:
        for idx, item in enumerate(shots[:12], 1):
            if not isinstance(item, dict):
                continue
            vis = str(item.get("visual") or item.get("description") or "").strip()
            if not vis:
                continue
            normalized_shots.append(
                {
                    "index": idx,
                    "title": str(item.get("title") or f"第 {idx} 镜").strip(),
                    "visual": vis,
                    "camera": str(item.get("camera") or "电影级自然运镜").strip(),
                    "dialogue": str(item.get("dialogue") or "").strip(),
                    "sfx": str(item.get("sfx") or "同期环境音效").strip(),
                    "duration_sec": max(3.0, float(item.get("duration_sec") or shot_duration_sec or 15.0)),
                }
            )
    else:
        normalized_shots = parse_raw_script_into_shots(
            raw_script, default_shot_duration_sec=shot_duration_sec
        )

    if not normalized_shots:
        raise ValueError("未解析到有效分镜内容，请提供至少 1 行分镜脚本或 shots 列表")

    lane_w = 580.0
    lane_h = 860.0
    lane_gap = 128.0
    total_w = len(normalized_shots) * lane_w + max(0, len(normalized_shots) - 1) * lane_gap
    bible_h = 240.0

    created_elements: List[Dict[str, Any]] = []
    frame_ids: List[str] = []
    srt_items: List[Dict[str, Any]] = []

    async with canvas_lock_manager.lock_canvas(canvas_id):
        canvas = await active_db.get_canvas_data(canvas_id)
        if canvas is None:
            raise FileNotFoundError(f"画布不存在: {canvas_id}")
        data = canvas.get("data") or {}
        elements: List[Dict[str, Any]] = data.setdefault("elements", [])
        data.setdefault("files", {})

        ox_i, oy_i = await find_next_best_element_position(
            data, int(total_w), int(bible_h + lane_h + 100)
        )
        ox, oy = float(ox_i), float(oy_i)
        stamp = f"{int(time.time() * 1000) % 1000000}_{random.randint(100, 999)}"

        # 1. 顶部角色定妆与全片视觉锚定框
        bible_fid = f"frame_bible_{stamp}"
        bible_frame = _make_base_shape(
            bible_fid,
            "frame",
            ox,
            oy,
            max(lane_w, min(total_w, 1288.0)),
            bible_h,
            stroke_color="#64748b",
        )
        bible_frame["name"] = f"《{film_title}》角色定妆与视觉总锚点"
        elements.append(bible_frame)
        created_elements.append(bible_frame)

        anchor_txt = (
            f"【片名】《{film_title}》（共 {len(normalized_shots)} 镜）\n"
            f"【人物与美术定妆设定】{character_anchor_desc.strip() or '保持全片主角面容、服装材质、时代器物与主光色温前后统一；跨镜使用尾帧接力锁定连贯性。'}"
        )
        bible_cards = _make_bound_card(
            f"card_bible_{stamp}",
            ox + 28.0,
            oy + 36.0,
            max(520.0, min(total_w, 1288.0) - 56.0),
            bible_h - 60.0,
            anchor_txt,
            stroke_color="#0f766e",
            bg_color="#f0fdfa",
            font_size=15,
            frame_id=bible_fid,
        )
        elements.extend(bible_cards)
        created_elements.extend(bible_cards)

        # 2. 横向分镜泳道、脚本卡、块箭头与递增角标
        lanes_y = oy + bible_h + 72.0
        cursor_sec = 0.0
        badge_start = _next_callout_num(elements)

        for idx, shot in enumerate(normalized_shots):
            dur_s = float(shot["duration_sec"])
            end_sec = cursor_sec + dur_s
            lx = ox + idx * (lane_w + lane_gap)
            fid = f"frame_shot_{stamp}_{idx + 1}"
            frame_ids.append(fid)

            lane_frame = _make_base_shape(
                fid, "frame", lx, lanes_y, lane_w, lane_h, stroke_color="#94a3b8"
            )
            lane_frame["name"] = (
                f"{idx + 1:02d} · {shot['title']} ({cursor_sec:04.1f}s–{end_sec:04.1f}s)"
            )
            elements.append(lane_frame)
            created_elements.append(lane_frame)

            card_lines = [
                f"【{shot['title']} · {dur_s:.1f}s】",
                f"画面：{shot['visual']}",
                f"运镜：{shot['camera']}",
            ]
            if shot["dialogue"]:
                card_lines.append(f"台词：“{shot['dialogue']}”")
                srt_items.append(
                    {
                        "start": round(cursor_sec + 0.3, 2),
                        "end": round(max(cursor_sec + 1.0, end_sec - 0.3), 2),
                        "text": shot["dialogue"],
                    }
                )
            card_lines.append(f"音效：{shot['sfx']}")

            shot_cards = _make_bound_card(
                f"card_shot_{stamp}_{idx + 1}",
                lx + 24.0,
                lanes_y + 40.0,
                lane_w - 48.0,
                230.0,
                "\n".join(card_lines),
                stroke_color="#2563eb",
                bg_color="#eff6ff",
                font_size=14,
                frame_id=fid,
            )
            elements.extend(shot_cards)
            created_elements.extend(shot_cards)

            # 左上角递增序号角标
            bnum = badge_start + idx
            grp_id = f"sb_badge_{stamp}_{bnum}"
            circle = _make_base_shape(
                f"bc_{grp_id}",
                "ellipse",
                lx + 14.0,
                lanes_y + 14.0,
                34.0,
                34.0,
                stroke_color="#ffffff",
                bg_color="#ef4444",
                group_ids=[grp_id],
                frame_id=fid,
                custom_data={
                    "jaazType": "callout-badge",
                    "calloutNumber": bnum,
                    "targetElementId": shot_cards[0]["id"],
                },
            )
            btxt = _make_base_shape(
                f"bt_{grp_id}",
                "text",
                lx + 24.0,
                lanes_y + 21.0,
                16.0,
                20.0,
                stroke_color="#ffffff",
                stroke_width=1,
                group_ids=[grp_id],
                frame_id=fid,
                custom_data={"jaazType": "callout-badge-label", "calloutNumber": bnum},
            )
            btxt.update(
                {
                    "text": str(bnum),
                    "originalText": str(bnum),
                    "fontSize": 16,
                    "fontFamily": 2,
                    "textAlign": "center",
                    "verticalAlign": "middle",
                    "containerId": None,
                    "lineHeight": 1.25,
                    "autoResize": True,
                }
            )
            elements.extend([circle, btxt])
            created_elements.extend([circle, btxt])

            if idx < len(normalized_shots) - 1:
                barrow = _make_block_arrow_element(
                    f"barrow_{stamp}_{idx + 1}",
                    lx + lane_w + 22.0,
                    lanes_y + lane_h * 0.45,
                    width=lane_gap - 44.0,
                    height=42.0,
                )
                elements.append(barrow)
                created_elements.append(barrow)

            cursor_sec = end_sec

        await active_db.save_canvas_data(canvas_id, json.dumps(data))

    if session_id and created_elements:
        await broadcast_session_update(
            session_id,
            canvas_id,
            {
                "type": "canvas_elements_updated",
                "canvas_id": canvas_id,
                "elements": created_elements,
            },
        )

    total_dur = round(sum(float(s["duration_sec"]) for s in normalized_shots), 1)
    relay_instruction = (
        f"已在画布铺排《{film_title}》共 {len(normalized_shots)} 镜（总时长 {total_dur}s）。"
        "请先按角色设定框生成主角定妆锚点图，再依次生成各镜视频（跨镜调用 extract_video_frame 抽尾帧接力），"
        "最后调用 video_edit_and_stitch 精装合片。"
    )
    return {
        "canvas_id": canvas_id,
        "film_title": film_title,
        "shot_count": len(normalized_shots),
        "total_duration_sec": total_dur,
        "frame_ids": frame_ids,
        "created_element_count": len(created_elements),
        "subtitles": srt_items,
        "relay_instruction": relay_instruction,
    }
