from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .coordinates import deg_to_hms, deg_to_dms
from .utils import normalize_tns_name


@dataclass
class Target:
    name: str
    source_ids: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    ztf_id: str = ""
    iau_name: str = ""
    object_type: str = ""
    host: str = ""
    ra_deg: float | None = None
    dec_deg: float | None = None
    ra_hms: str = ""
    dec_dms: str = ""
    mag: float | None = None
    mag_filter: str = ""
    mag_note: str = ""
    peakmag: float | None = None
    peak_filter: str = ""
    peak_jd: float | None = None
    peak_date_utc: str = ""
    redshift: str = ""
    galactic_b: str = ""
    av: str = ""
    discovery_date: str = ""
    ztf_lc_png_url: str = ""
    ztf_finder_png_url: str = ""
    lasair_url: str = ""
    wiserep_query_url: str = ""
    visible_hours: float | None = None
    max_alt_deg: float | None = None
    best_time_utc: str = ""
    best_time_local: str = ""
    sun_alt_at_best: float | None = None
    moon_sep_at_best: float | None = None
    priority_score: float | None = None
    notes: list[str] = field(default_factory=list)

    def key(self) -> str:
        for value in (self.iau_name, self.name, self.ztf_id):
            if value and value != "-":
                return normalize_tns_name(value).lower()
        return self.name.lower()

    def update_mag(self, mag: float | None, source: str, filt: str = "", note: str = "") -> None:
        if mag is None:
            return
        if self.mag is None or mag < self.mag:
            self.mag = mag
            self.mag_filter = filt
            self.mag_note = f"{source}{': ' + note if note else ''}"

    def finalize(self) -> None:
        if not self.ra_hms and self.ra_deg is not None:
            self.ra_hms = deg_to_hms(self.ra_deg)
        if not self.dec_dms and self.dec_deg is not None:
            self.dec_dms = deg_to_dms(self.dec_deg)
        if self.ztf_id:
            self.aliases.add(self.ztf_id)
        if self.iau_name:
            self.aliases.add(self.iau_name)
        if self.name:
            self.aliases.add(self.name)

    def as_dict(self) -> dict[str, Any]:
        self.finalize()
        return {
            "name": self.name,
            "iau_name": self.iau_name,
            "ztf_id": self.ztf_id,
            "aliases": ";".join(sorted(a for a in self.aliases if a)),
            "sources": ";".join(sorted(self.source_ids)),
            "type": self.object_type,
            "host": self.host,
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
            "ra_hms": self.ra_hms,
            "dec_dms": self.dec_dms,
            "mag": self.mag,
            "mag_filter": self.mag_filter,
            "mag_note": self.mag_note,
            "peakmag": self.peakmag,
            "peak_filter": self.peak_filter,
            "peak_jd": self.peak_jd,
            "peak_date_utc": self.peak_date_utc,
            "redshift": self.redshift,
            "galactic_b": self.galactic_b,
            "av": self.av,
            "discovery_date": self.discovery_date,
            "visible_hours": self.visible_hours,
            "max_alt_deg": self.max_alt_deg,
            "best_time_utc": self.best_time_utc,
            "best_time_local": self.best_time_local,
            "sun_alt_at_best": self.sun_alt_at_best,
            "moon_sep_at_best": self.moon_sep_at_best,
            "priority_score": self.priority_score,
            "ztf_lc_png_url": self.ztf_lc_png_url,
            "ztf_finder_png_url": self.ztf_finder_png_url,
            "lasair_url": self.lasair_url,
            "wiserep_query_url": self.wiserep_query_url,
            "notes": " | ".join(self.notes),
        }


def merge_target(base: Target, incoming: Target) -> Target:
    base.source_ids |= incoming.source_ids
    base.aliases |= incoming.aliases
    for attr in (
        "ztf_id",
        "iau_name",
        "object_type",
        "host",
        "ra_hms",
        "dec_dms",
        "mag_filter",
        "peak_filter",
        "peak_date_utc",
        "redshift",
        "galactic_b",
        "av",
        "discovery_date",
        "ztf_lc_png_url",
        "ztf_finder_png_url",
        "lasair_url",
        "wiserep_query_url",
    ):
        if not getattr(base, attr) and getattr(incoming, attr):
            setattr(base, attr, getattr(incoming, attr))
    if base.ra_deg is None and incoming.ra_deg is not None:
        base.ra_deg = incoming.ra_deg
    if base.dec_deg is None and incoming.dec_deg is not None:
        base.dec_deg = incoming.dec_deg
    if base.peakmag is None and incoming.peakmag is not None:
        base.peakmag = incoming.peakmag
    if base.peak_jd is None and incoming.peak_jd is not None:
        base.peak_jd = incoming.peak_jd
    base.update_mag(incoming.mag, incoming.mag_note or "merged", incoming.mag_filter)
    base.notes.extend(n for n in incoming.notes if n not in base.notes)
    if base.name == "unknown" and incoming.name != "unknown":
        base.name = incoming.name
    return base


def merge_targets(targets: Iterable[Target]) -> list[Target]:
    merged: dict[str, Target] = {}
    ztf_to_key: dict[str, str] = {}
    for target in targets:
        target.finalize()
        key = target.key()
        if target.ztf_id and target.ztf_id.lower() in ztf_to_key:
            key = ztf_to_key[target.ztf_id.lower()]
        if key in merged:
            merge_target(merged[key], target)
        else:
            merged[key] = target
        if merged[key].ztf_id:
            ztf_to_key[merged[key].ztf_id.lower()] = key
    return list(merged.values())


def filter_targets(targets: list[Target], *, min_dec: float, mag_limit: float, min_mag: float) -> list[Target]:
    selected: list[Target] = []
    for target in targets:
        target.finalize()
        if target.mag is None or target.mag > mag_limit:
            continue
        if target.mag is not None and target.mag < min_mag:
            continue
        if target.dec_deg is None or target.dec_deg < min_dec:
            continue
        selected.append(target)
    return selected


def target_sort_key(target: Target, rank_by: str) -> tuple[Any, ...]:
    mag = target.mag if target.mag is not None else 99.0
    priority = target.priority_score if target.priority_score is not None else -999.0
    visible_hours = target.visible_hours if target.visible_hours is not None else -1.0
    max_alt = target.max_alt_deg if target.max_alt_deg is not None else -90.0
    if rank_by == "priority":
        return (-priority, mag, target.name)
    if rank_by == "visible_hours":
        return (-visible_hours, mag, -priority, target.name)
    if rank_by == "max_alt":
        return (-max_alt, mag, -priority, target.name)
    if rank_by == "name":
        return (target.name, mag)
    return (mag, -priority, target.name)
