from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any

from .time_utils import altitude_deg, datetime_to_jd, sun_ra_dec_approx
from .utils import warn


def compute_observability_simple(
    targets: list[Any],
    date: str,
    *,
    site_lat: float,
    site_lon: float,
    tz_offset: float,
    time_step_minutes: int,
    sun_alt_limit: float,
    min_alt: float,
    mag_limit: float,
) -> None:
    warn("Using approximate pure-Python observability; install astropy for higher precision and Moon separation.")
    local_date = dt.date.fromisoformat(date)
    tz = dt.timezone(dt.timedelta(hours=tz_offset))
    start_local = dt.datetime.combine(local_date, dt.time(18, 0), tzinfo=tz)
    end_local = dt.datetime.combine(local_date + dt.timedelta(days=1), dt.time(6, 0), tzinfo=tz)
    start_utc = start_local.astimezone(dt.timezone.utc)
    end_utc = end_local.astimezone(dt.timezone.utc)
    step = dt.timedelta(minutes=time_step_minutes)
    times_dt: list[dt.datetime] = []
    current = start_utc
    while current <= end_utc:
        times_dt.append(current)
        current += step
    jds = [datetime_to_jd(t) for t in times_dt]
    sun_alt = []
    for jd in jds:
        sun_ra, sun_dec = sun_ra_dec_approx(jd)
        sun_alt.append(altitude_deg(sun_ra, sun_dec, jd, site_lat, site_lon))
    dark_mask = [alt < sun_alt_limit for alt in sun_alt]

    for target in targets:
        if target.ra_deg is None or target.dec_deg is None:
            continue
        alt = [altitude_deg(target.ra_deg, target.dec_deg, jd, site_lat, site_lon) for jd in jds]
        visible_mask = [a > min_alt and dark for a, dark in zip(alt, dark_mask)]
        step_hours = time_step_minutes / 60.0
        target.visible_hours = round(sum(1 for ok in visible_mask if ok) * step_hours, 2)
        if any(visible_mask):
            idx_candidates = [i for i, ok in enumerate(visible_mask) if ok]
            best_idx = max(idx_candidates, key=lambda i: alt[i])
        elif any(dark_mask):
            idx_candidates = [i for i, ok in enumerate(dark_mask) if ok]
            best_idx = max(idx_candidates, key=lambda i: alt[i])
        else:
            best_idx = max(range(len(alt)), key=lambda i: alt[i])
        target.max_alt_deg = round(float(alt[best_idx]), 1)
        target.best_time_utc = times_dt[best_idx].strftime("%Y-%m-%d %H:%M")
        target.best_time_local = times_dt[best_idx].astimezone(tz).strftime("%Y-%m-%d %H:%M")
        target.sun_alt_at_best = round(float(sun_alt[best_idx]), 1)
        mag = target.mag if target.mag is not None else mag_limit
        target.priority_score = round(
            10.0 * (target.visible_hours or 0.0)
            + 0.35 * max(target.max_alt_deg or 0.0, 0.0)
            + 6.0 * max(mag_limit - mag, 0.0),
            2,
        )


def compute_observability(
    targets: list[Any],
    date: str,
    *,
    site_lat: float,
    site_lon: float,
    site_elevation_m: float,
    tz_offset: float,
    time_step_minutes: int,
    sun_alt_limit: float,
    min_alt: float,
    mag_limit: float,
) -> None:
    if not targets:
        return
    try:
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body, get_sun
        from astropy.time import Time
        from astropy.utils import iers

        iers.conf.auto_download = False
    except Exception as exc:  # noqa: BLE001
        warn(f"Astropy observability unavailable ({exc})")
        compute_observability_simple(
            targets, date,
            site_lat=site_lat, site_lon=site_lon,
            tz_offset=tz_offset, time_step_minutes=time_step_minutes,
            sun_alt_limit=sun_alt_limit, min_alt=min_alt, mag_limit=mag_limit,
        )
        return

    local_date = dt.date.fromisoformat(date)
    tz = dt.timezone(dt.timedelta(hours=tz_offset))
    start_local = dt.datetime.combine(local_date, dt.time(18, 0), tzinfo=tz)
    end_local = dt.datetime.combine(local_date + dt.timedelta(days=1), dt.time(6, 0), tzinfo=tz)
    start_utc = start_local.astimezone(dt.timezone.utc)
    end_utc = end_local.astimezone(dt.timezone.utc)
    step = dt.timedelta(minutes=time_step_minutes)
    times_dt: list[dt.datetime] = []
    current = start_utc
    while current <= end_utc:
        times_dt.append(current)
        current += step
    times = Time(times_dt)
    location = EarthLocation(
        lat=site_lat * u.deg,
        lon=site_lon * u.deg,
        height=site_elevation_m * u.m,
    )
    frame = AltAz(obstime=times, location=location)
    sun_alt = get_sun(times).transform_to(frame).alt.deg
    dark_mask = sun_alt < sun_alt_limit
    try:
        moon_coord = get_body("moon", times, location=location).icrs
    except Exception as exc:  # noqa: BLE001
        moon_coord = None
        warn(f"Moon separation unavailable ({exc})")

    for target in targets:
        if target.ra_deg is None or target.dec_deg is None:
            continue
        coord = SkyCoord(ra=target.ra_deg * u.deg, dec=target.dec_deg * u.deg)
        altaz = coord.transform_to(frame)
        alt = altaz.alt.deg
        visible_mask = (alt > min_alt) & dark_mask
        step_hours = time_step_minutes / 60.0
        target.visible_hours = round(float(visible_mask.sum()) * step_hours, 2)
        if visible_mask.any():
            idx_candidates = [i for i, ok in enumerate(visible_mask) if ok]
            best_idx = max(idx_candidates, key=lambda i: alt[i])
        elif dark_mask.any():
            idx_candidates = [i for i, ok in enumerate(dark_mask) if ok]
            best_idx = max(idx_candidates, key=lambda i: alt[i])
        else:
            best_idx = int(max(range(len(alt)), key=lambda i: alt[i]))
        target.max_alt_deg = round(float(alt[best_idx]), 1)
        target.best_time_utc = times_dt[best_idx].strftime("%Y-%m-%d %H:%M")
        target.best_time_local = times_dt[best_idx].astimezone(tz).strftime("%Y-%m-%d %H:%M")
        target.sun_alt_at_best = round(float(sun_alt[best_idx]), 1)
        if moon_coord is not None:
            sep = coord.separation(moon_coord[best_idx]).deg
            target.moon_sep_at_best = round(float(sep), 1)
        mag = target.mag if target.mag is not None else mag_limit
        moon_penalty = 0.0
        if target.moon_sep_at_best is not None and target.moon_sep_at_best < 30:
            moon_penalty = (30 - target.moon_sep_at_best) * 0.5
        target.priority_score = round(
            10.0 * (target.visible_hours or 0.0)
            + 0.35 * max(target.max_alt_deg or 0.0, 0.0)
            + 6.0 * max(mag_limit - mag, 0.0)
            - moon_penalty,
            2,
        )
