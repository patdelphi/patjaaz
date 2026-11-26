"""程序说明：FFmpeg 成片精装滤镜构建器（支持 EBU R128 响度均衡、Windows 路径转义硬烧录字幕、片头标题渐显与片尾淡出）。"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple


def format_srt_timestamp(seconds: float) -> str:
    """将浮点秒数格式化为标准 SRT 时间轴字符串 HH:MM:SS,mmm。"""
    clamped = max(0.0, float(seconds))
    total_ms = int(round(clamped * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt_content(subtitles: List[Dict[str, Any]]) -> str:
    """将字幕条目列表（start, end, text）序列化为 UTF-8 SRT 文本。"""
    blocks: List[str] = []
    idx = 1
    for item in subtitles or []:
        if not isinstance(item, dict):
            continue
        txt = str(item.get("text") or "").strip()
        if not txt:
            continue
        start_s = float(item.get("start") or 0.0)
        end_s = max(start_s + 0.5, float(item.get("end") or (start_s + 3.0)))
        blocks.append(
            f"{idx}\n{format_srt_timestamp(start_s)} --> {format_srt_timestamp(end_s)}\n{txt}\n"
        )
        idx += 1
    return "\n".join(blocks)


def escape_ffmpeg_filter_path(file_path: str) -> str:
    """将本地文件路径转义为 FFmpeg subtitles / fontfile 滤镜在 Windows 与 Unix 下均可解析的格式。"""
    normalized = str(file_path or "").replace("\\", "/")
    # FFmpeg 滤镜语法中反斜杠、单引号、冒号、方括号与分号具有特殊含义，必须逐一转义
    escaped = (
        normalized.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(",", r"\,")
        .replace(";", r"\;")
    )
    return escaped


def escape_ffmpeg_drawtext(text: str) -> str:
    """转义 FFmpeg drawtext 滤镜中的文本常量，避免冒号、单引号或换行导致解析报错。"""
    cleaned = str(text or "").strip().replace("\r", "").replace("\n", " ")
    return (
        cleaned.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
        .replace(",", r"\,")
        .replace(";", r"\;")
    )


def resolve_default_cjk_font_path() -> Optional[str]:
    """定位本机可用的中文字体文件供 drawtext 片头标题渲染使用。"""
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def build_post_concat_finishing_filters(
    v_in_label: str,
    a_in_label: Optional[str],
    *,
    total_duration_sec: float,
    burn_srt_path: Optional[str] = None,
    intro_title: Optional[str] = None,
    fade_out_outro_sec: float = 0.0,
    normalize_audio_loudness: bool = False,
) -> Tuple[List[str], str, Optional[str]]:
    """在 concat 输出标签之后追加字幕硬烧录、片头标题渐显、片尾淡出与 EBU R128 响度均衡滤镜链。"""
    clauses: List[str] = []
    v_ops: List[str] = []
    a_ops: List[str] = []

    title_clean = str(intro_title or "").strip()
    if title_clean:
        v_ops.append("fade=t=in:st=0:d=0.600")
        font_path = resolve_default_cjk_font_path()
        escaped_txt = escape_ffmpeg_drawtext(title_clean[:60])
        if font_path:
            esc_font = escape_ffmpeg_filter_path(font_path)
            v_ops.append(
                f"drawtext=fontfile='{esc_font}':text='{escaped_txt}':"
                "fontcolor=white:fontsize=38:borderw=2:bordercolor=black@0.75:"
                "x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t\\,0.15\\,2.65)'"
            )
        else:
            v_ops.append(
                f"drawtext=text='{escaped_txt}':fontcolor=white:fontsize=36:"
                "x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t\\,0.15\\,2.65)'"
            )

    if burn_srt_path:
        esc_srt = escape_ffmpeg_filter_path(burn_srt_path)
        v_ops.append(
            f"subtitles='{esc_srt}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00101010,Outline=2,Shadow=1,MarginV=24'"
        )

    outro_d = max(0.0, round(float(fade_out_outro_sec or 0.0), 3))
    if outro_d > 0.0 and total_duration_sec > outro_d + 0.25:
        out_st = max(0.0, total_duration_sec - outro_d)
        v_ops.append(f"fade=t=out:st={out_st:.3f}:d={outro_d:.3f}")
        if a_in_label:
            a_ops.append(f"afade=t=out:st={out_st:.3f}:d={outro_d:.3f}")

    if a_in_label and normalize_audio_loudness:
        # EBU R128 流媒体标准响度目标（-16 LUFS，真峰值上限 -1.5 dBTP）
        a_ops.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    final_v = v_in_label
    if v_ops:
        final_v = "[vfin]"
        clauses.append(f"{v_in_label}{','.join(v_ops)}{final_v}")

    final_a = a_in_label
    if a_in_label and a_ops:
        final_a = "[afin]"
        clauses.append(f"{a_in_label}{','.join(a_ops)}{final_a}")

    return clauses, final_v, final_a
