from __future__ import annotations

import datetime as dt
import math


def jd_to_iso(jd: float | None) -> str:
    if jd is None:
        return ""
    try:
        from astropy.time import Time

        return Time(jd, format="jd", scale="utc").iso
    except Exception:
        j = int(jd + 0.5)
        f = jd + 0.5 - j
        if j >= 2299161:
            a = int((j - 1867216.25) / 36524.25)
            j += 1 + a - int(a / 4)
        b = j + 1524
        c = int((b - 122.1) / 365.25)
        d = int(365.25 * c)
        e = int((b - d) / 30.6001)
        day = b - d - int(30.6001 * e) + f
        month = e - 1 if e < 14 else e - 13
        year = c - 4716 if month > 2 else c - 4715
        return f"{year:04d}-{month:02d}-{int(day):02d}"


def datetime_to_jd(moment: dt.datetime) -> float:
    moment = moment.astimezone(dt.timezone.utc)
    year = moment.year
    month = moment.month
    day = moment.day + (
        moment.hour + (moment.minute + (moment.second + moment.microsecond / 1e6) / 60.0) / 60.0
    ) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + b
        - 1524.5
    )


def gmst_deg(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )
    return gmst % 360.0


def sun_ra_dec_approx(jd: float) -> tuple[float, float]:
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    m = math.radians((357.52911 + t * (35999.05029 - 0.0001537 * t)) % 360.0)
    c = (
        math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * m) * (0.019993 - 0.000101 * t)
        + math.sin(3 * m) * 0.000289
    )
    true_long = l0 + c
    omega = math.radians(125.04 - 1934.136 * t)
    lambda_app = math.radians(true_long - 0.00569 - 0.00478 * math.sin(omega))
    epsilon0 = 23.0 + (26.0 + ((21.448 - t * (46.815 + t * (0.00059 - t * 0.001813)))) / 60.0) / 60.0
    epsilon = math.radians(epsilon0 + 0.00256 * math.cos(omega))
    ra = math.degrees(math.atan2(math.cos(epsilon) * math.sin(lambda_app), math.cos(lambda_app))) % 360.0
    dec = math.degrees(math.asin(math.sin(epsilon) * math.sin(lambda_app)))
    return ra, dec


def altitude_deg(ra_deg: float, dec_deg: float, jd: float, lat_deg: float, lon_deg: float) -> float:
    lst = (gmst_deg(jd) + lon_deg) % 360.0
    ha = ((lst - ra_deg + 180.0) % 360.0) - 180.0
    lat = math.radians(lat_deg)
    dec = math.radians(dec_deg)
    ha_rad = math.radians(ha)
    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha_rad)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))


def now_jd() -> float:
    return datetime_to_jd(dt.datetime.now(dt.timezone.utc))
