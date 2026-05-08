from __future__ import annotations

from pathlib import Path

from .utils import info, mkdir, warn


def _target_arrow_points(
    target_x: float,
    target_y: float,
    data_shape: tuple[int, ...],
    *,
    clearance_px: float = 18.0,
    length_px: float = 80.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return arrow start/end pixels that point near, but not over, the target."""
    import math

    ny, nx = data_shape[-2], data_shape[-1]
    margin = 8.0
    unit = 1.0 / math.sqrt(2.0)
    # Prefer an arrow from upper-left; fall back to other corners near image edges.
    offsets = [(-unit, unit), (unit, unit), (-unit, -unit), (unit, -unit)]

    for ox, oy in offsets:
        start = (target_x + ox * length_px, target_y + oy * length_px)
        end = (target_x + ox * clearance_px, target_y + oy * clearance_px)
        if (
            margin <= start[0] <= nx - margin
            and margin <= start[1] <= ny - margin
            and margin <= end[0] <= nx - margin
            and margin <= end[1] <= ny - margin
        ):
            return start, end

    # Last-resort clamp for targets near the frame boundary.
    ox, oy = offsets[0]
    start = (target_x + ox * length_px, target_y + oy * length_px)
    end = (target_x + ox * clearance_px, target_y + oy * clearance_px)
    return (
        (min(max(start[0], margin), nx - margin), min(max(start[1], margin), ny - margin)),
        (min(max(end[0], margin), nx - margin), min(max(end[1], margin), ny - margin)),
    )


def _draw_target_arrow(ax, target_x: float, target_y: float, data_shape: tuple[int, ...]) -> None:
    start, end = _target_arrow_points(target_x, target_y, data_shape)
    ax.annotate(
        "",
        xy=end,
        xytext=start,
        arrowprops={
            "arrowstyle": "-|>",
            "color": "red",
            "lw": 2.2,
            "mutation_scale": 18,
            "shrinkA": 0,
            "shrinkB": 0,
        },
        zorder=8,
    )


def _compass_vectors(wcs, x0: float, y0: float, length_arcmin: float) -> dict[str, tuple[float, float]] | None:
    """Return pixel endpoints for local north/east compass arrows."""
    try:
        import numpy as np
        from astropy import units as u
        from astropy.coordinates import SkyCoord

        base_world = wcs.pixel_to_world(x0, y0)
        base = SkyCoord(base_world)
        north = base.directional_offset_by(0 * u.deg, length_arcmin * u.arcmin)
        east = base.directional_offset_by(90 * u.deg, length_arcmin * u.arcmin)
        xn, yn = wcs.world_to_pixel(north)
        xe, ye = wcs.world_to_pixel(east)
        values = (float(xn), float(yn), float(xe), float(ye))
        if not all(np.isfinite(values)):
            return None
        return {"N": (values[0], values[1]), "E": (values[2], values[3])}
    except Exception:
        return None


def _draw_compass(ax, wcs, data_shape: tuple[int, ...], fov_arcmin: float) -> bool:
    if wcs is None or not getattr(wcs, "is_celestial", False):
        return False
    ny, nx = data_shape[-2], data_shape[-1]
    x0 = nx * 0.14
    y0 = ny * 0.14
    length_arcmin = min(1.5, max(0.4, fov_arcmin * 0.10))
    vectors = _compass_vectors(wcs, x0, y0, length_arcmin)
    if vectors is None:
        return False

    arrowprops = {
        "arrowstyle": "-|>",
        "color": "#ffd84d",
        "lw": 2.0,
        "shrinkA": 0,
        "shrinkB": 0,
    }
    label_box = {
        "boxstyle": "round,pad=0.15",
        "facecolor": "black",
        "edgecolor": "none",
        "alpha": 0.55,
    }
    for label, (x1, y1) in vectors.items():
        dx, dy = x1 - x0, y1 - y0
        ax.plot(
            [x0 - dx * 0.35, x0],
            [y0 - dy * 0.35, y0],
            color="#ffd84d",
            lw=2.0,
            solid_capstyle="round",
            zorder=6,
        )
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=arrowprops, zorder=6)
        ax.text(
            x1 + dx * 0.12,
            y1 + dy * 0.12,
            label,
            color="#ffd84d",
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            bbox=label_box,
            zorder=7,
        )
    ax.plot(x0, y0, "o", color="#ffd84d", markersize=3, zorder=7)
    return True


def generate_finder_chart(
    ra_deg: float,
    dec_deg: float,
    target_name: str,
    output_dir: Path,
    *,
    fov_arcmin: float = 10.0,
    pixels: int = 500,
    survey: str = "DSS2 Red",
    overwrite: bool = False,
) -> Path | None:
    """Generate a finder chart using astroquery SkyView + matplotlib.

    Downloads a DSS2 survey cutout and plots it with WCS coordinates,
    a target arrow, scale bar, compass, and coordinate labels.

    Parameters
    ----------
    ra_deg, dec_deg : float
        Target coordinates in decimal degrees (ICRS/J2000).
    target_name : str
        Display label for the chart title.
    output_dir : Path
        Directory to save the output PNG.
    fov_arcmin : float
        Field of view in arcminutes (default 10).
    pixels : int
        Output image size in pixels (square).
    survey : str
        SkyView survey name (default "DSS2 Red").
    overwrite : bool
        Overwrite existing file.

    Returns
    -------
    Path or None
        Path to the saved PNG, or None on failure.
    """
    dest = output_dir / f"finder_astroquery_{survey.replace(' ', '_')}.png"
    if dest.exists() and not overwrite:
        info(f"Finder chart already exists: {dest}")
        return dest

    try:
        import numpy as np
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from astropy import units as u
        from astropy.visualization import ZScaleInterval
        from astropy.wcs import WCS
        from astroquery.skyview import SkyView
    except Exception as exc:
        warn(f"Finder chart deps not available: {exc}")
        return None

    info(f"Generating finder chart ({survey}, {fov_arcmin}' FOV) for {target_name}")

    # ── Download image from SkyView ──
    try:
        hdu_lists = SkyView.get_images(
            position=f"{ra_deg} {dec_deg}",
            survey=survey,
            radius=fov_arcmin * u.arcmin,
            pixels=str(pixels),
        )
        hdul = hdu_lists[0]
        hdu = hdul[0]
        data = np.array(hdu.data, dtype=np.float64)
    except Exception as exc:
        warn(f"SkyView query failed: {exc}")
        return None

    # ── WCS ──
    try:
        wcs = WCS(hdu.header)
    except Exception:
        wcs = None

    # ── Plot ──
    fig = plt.figure(figsize=(8, 8), facecolor="white")

    if wcs is not None and wcs.is_celestial:
        ax = fig.add_subplot(111, projection=wcs)
    else:
        ax = fig.add_subplot(111)

    # ZScale stretch for good contrast
    interval = ZScaleInterval()
    try:
        vmin, vmax = interval.get_limits(data)
    except Exception:
        vmin, vmax = np.percentile(data[np.isfinite(data)], [5, 95])

    ax.imshow(data, cmap="gray", vmin=vmin, vmax=vmax, origin="lower", interpolation="nearest")

    # ── Arrow pointing to target ──
    if wcs is not None and wcs.is_celestial:
        target_x, target_y = wcs.world_to_pixel_values(ra_deg, dec_deg)
    else:
        target_x, target_y = pixels / 2, pixels / 2
    _draw_target_arrow(ax, float(target_x), float(target_y), data.shape)

    # ── Local N/E compass ──
    if not _draw_compass(ax, wcs, data.shape, fov_arcmin):
        warn("Finder chart compass skipped: celestial WCS unavailable")

    # ── Scale bar ──
    bar_arcmin = max(0.5, fov_arcmin / 20)
    bar_pix = bar_arcmin / (fov_arcmin / pixels)
    bar_y = pixels * 0.08
    bar_x_start = pixels * 0.75
    bar_x_end = bar_x_start + bar_pix
    ax.plot([bar_x_start, bar_x_end], [bar_y, bar_y], "w-", lw=4)
    ax.text(
        (bar_x_start + bar_x_end) / 2, bar_y + pixels * 0.015,
        f"{bar_arcmin:.1f}'", color="white", ha="center", va="bottom",
        fontsize=10, fontweight="bold",
    )

    # ── Labels ──
    ax.set_xlabel("RA (J2000)")
    ax.set_ylabel("Dec (J2000)")
    ax.set_title(target_name, fontsize=13)

    # ── Save ──
    mkdir(dest.parent)
    fig.savefig(dest, dpi=150, bbox_inches="tight", facecolor="white", edgecolor="none")
    plt.close(fig)

    info(f"Finder chart saved → {dest}")
    return dest
