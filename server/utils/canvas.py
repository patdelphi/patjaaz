"""程序说明：计算画布新增媒体元素的最佳放置坐标，自动避让已有的文字框、图形、箭头、画框与媒体元素。"""
from typing import Any, Dict, List, Tuple


def _elem_bounds(element: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """提取元素的归一化包围盒 (left, top, right, bottom)，兼容负宽高的箭头或线条。"""
    x = float(element.get("x") or 0)
    y = float(element.get("y") or 0)
    w = float(element.get("width") or 0)
    h = float(element.get("height") or 0)
    left = min(x, x + w)
    right = max(x, x + w)
    top = min(y, y + h)
    bottom = max(y, y + h)
    return left, top, right, bottom


def _boxes_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    """判断两个矩形包围盒是否存在面积重叠。"""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


async def find_next_best_element_position(
    canvas_data: Dict[str, Any],
    max_num_per_row: int = 4,
    spacing: int = 40,
    target_width: int = 1024,
    target_height: int = 1024,
) -> Tuple[float, float]:
    """计算画布下一个新媒体元素的坐标：按行排列媒体，并自动避让已有文字框与图形元素。"""
    raw_elements = (canvas_data or {}).get("elements") or []
    active_elements: List[Dict[str, Any]] = [
        e for e in raw_elements if isinstance(e, dict) and not e.get("isDeleted")
    ]
    if not active_elements:
        return 0, 0

    media_elements = [
        e for e in active_elements if e.get("type") in ("image", "embeddable", "video")
    ]

    if media_elements:
        media_elements.sort(key=lambda e: (_elem_bounds(e)[1], _elem_bounds(e)[0]))
        rows: List[List[Dict[str, Any]]] = []
        for element in media_elements:
            _, top, _, bottom = _elem_bounds(element)
            placed = False
            for row in rows:
                if any(
                    max(top, _elem_bounds(r)[1]) < min(bottom, _elem_bounds(r)[3])
                    for r in row
                ):
                    row.append(element)
                    placed = True
                    break
            if not placed:
                rows.append([element])

        rows.sort(key=lambda row: sum(_elem_bounds(e)[1] for e in row) / len(row))
        base_x = min(_elem_bounds(e)[0] for row in rows for e in row)
        last_row = sorted(rows[-1], key=lambda e: _elem_bounds(e)[0])

        if len(last_row) < max_num_per_row:
            cand_x = max(_elem_bounds(e)[2] for e in last_row) + spacing
            cand_y = min(_elem_bounds(e)[1] for e in last_row)
        else:
            cand_x = base_x
            cand_y = max(_elem_bounds(e)[3] for e in last_row) + spacing
    else:
        # 画布仅有文字框、形状、画框或箭头时，将首个生成作品放在现有内容右侧（过宽则放下方）
        all_bounds = [_elem_bounds(e) for e in active_elements]
        min_x = min(b[0] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_r = max(b[2] for b in all_bounds)
        max_b = max(b[3] for b in all_bounds)
        if max_r - min_x <= 2000:
            base_x = max_r + spacing
            cand_x, cand_y = base_x, min_y
        else:
            base_x = min_x
            cand_x, cand_y = base_x, max_b + spacing

    w = max(1.0, float(target_width or 1024))
    h = max(1.0, float(target_height or 1024))
    obstacle_bounds = [_elem_bounds(e) for e in active_elements]
    max_row_span = base_x + max_num_per_row * (w + spacing)

    for _ in range(24):
        target_box = (cand_x, cand_y, cand_x + w, cand_y + h)
        hits = [b for b in obstacle_bounds if _boxes_overlap(target_box, b)]
        if not hits:
            break
        next_x = max(b[2] for b in hits) + spacing
        if next_x <= max_row_span:
            cand_x = next_x
        else:
            cand_x = base_x
            cand_y = max(b[3] for b in hits) + spacing

    return round(cand_x, 2), round(cand_y, 2)
