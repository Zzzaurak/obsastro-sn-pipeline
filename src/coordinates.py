from __future__ import annotations

import math
import re


def sexagesimal_to_deg(value: str, is_ra: bool) -> float | None:
    if not value:
        return None
    raw = (
        value.strip()
        .replace("h", ":")
        .replace("m", ":")
        .replace("s", "")
        .replace("d", ":")
        .replace("'", ":")
        .replace('"', "")
        .replace("\u2212", "-")
    )
    raw = raw.replace("::", ":")
    sign = -1.0 if raw.startswith("-") else 1.0
    raw = raw.lstrip("+-")
    parts = [p for p in re.split(r"[:\s]+", raw) if p]
    if not parts:
        return None
    try:
        nums = [float(p) for p in parts[:3]]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.append(0.0)
    value_deg = nums[0] + nums[1] / 60.0 + nums[2] / 3600.0
    if is_ra:
        return (value_deg * 15.0) % 360.0
    return sign * value_deg


def deg_to_hms(ra_deg: float | None) -> str:
    if ra_deg is None or not math.isfinite(ra_deg):
        return ""
    hours = (ra_deg % 360.0) / 15.0
    h = int(hours)
    m_float = (hours - h) * 60.0
    m = int(m_float)
    s = (m_float - m) * 60.0
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def deg_to_dms(dec_deg: float | None) -> str:
    if dec_deg is None or not math.isfinite(dec_deg):
        return ""
    sign = "+" if dec_deg >= 0 else "-"
    value = abs(dec_deg)
    d = int(value)
    m_float = (value - d) * 60.0
    m = int(m_float)
    s = (m_float - m) * 60.0
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"
