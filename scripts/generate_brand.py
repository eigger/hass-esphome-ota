"""Generate Home Assistant brand images for ESPHome OTA.

The artwork is an original geometric brand mark on a dark navy rounded square:
a cyan smart-home pentagon housing a white circuit-comb trace, paired with a
golden OTA upload arrow badge (outlined in negative space) and wireless signal
arcs. Drawn from geometric primitives at 4x scale and downsampled, so no source
image, external font file, or network access is needed. Run with Pillow 12.3.0
for reproducible PNGs.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND = Path(__file__).resolve().parents[1] / "custom_components/esphome_ota/brand"
SIZE = 512
SCALE = 4
NAVY = "#1b2a41"
CYAN = "#18bcf2"
WHITE = "#ffffff"
YELLOW = "#ffd23f"
GOLD = "#f2a900"
WORDMARK = "#18bcf2"


def _rounded_polygon(
    points: list[tuple[float, float]],
    radii: list[float] | float,
    steps: int = 24,
) -> list[tuple[float, float]]:
    """Return polygon vertices with mathematically rounded corners."""
    n = len(points)
    if isinstance(radii, (int, float)):
        radii = [float(radii)] * n
    poly_pts: list[tuple[float, float]] = []
    for i in range(n):
        r = radii[i]
        if r <= 0:
            poly_pts.append(points[i])
            continue
        p_prev = points[(i - 1) % n]
        p_curr = points[i]
        p_next = points[(i + 1) % n]

        v1 = (p_prev[0] - p_curr[0], p_prev[1] - p_curr[1])
        v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        u1 = (v1[0] / l1, v1[1] / l1)
        u2 = (v2[0] / l2, v2[1] / l2)

        dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        half_ang = math.acos(dot) / 2.0
        dist = min(r / math.tan(half_ang), l1 * 0.45, l2 * 0.45)
        eff_r = dist * math.tan(half_ang)
        t1 = (p_curr[0] + u1[0] * dist, p_curr[1] + u1[1] * dist)
        t2 = (p_curr[0] + u2[0] * dist, p_curr[1] + u2[1] * dist)

        bis = (u1[0] + u2[0], u1[1] + u2[1])
        bl = math.hypot(*bis)
        ub = (bis[0] / bl, bis[1] / bl)
        c_dist = eff_r / math.sin(half_ang)
        center = (p_curr[0] + ub[0] * c_dist, p_curr[1] + ub[1] * c_dist)

        a1 = math.atan2(t1[1] - center[1], t1[0] - center[0])
        a2 = math.atan2(t2[1] - center[1], t2[0] - center[0])
        da = a2 - a1
        while da <= -math.pi:
            da += 2 * math.pi
        while da > math.pi:
            da -= 2 * math.pi

        for s_idx in range(steps + 1):
            a = a1 + da * s_idx / steps
            poly_pts.append(
                (center[0] + eff_r * math.cos(a), center[1] + eff_r * math.sin(a))
            )
    return poly_pts


def _draw_thick_line(
    d: ImageDraw.ImageDraw,
    p0: tuple[float, float],
    p1: tuple[float, float],
    width: float,
    fill: str,
) -> None:
    """Draw a line segment with round caps."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    r = width / 2.0
    if length > 0:
        nx, ny = -dy / length * r, dx / length * r
        d.polygon(
            [
                (x0 + nx, y0 + ny),
                (x1 + nx, y1 + ny),
                (x1 - nx, y1 - ny),
                (x0 - nx, y0 - ny),
            ],
            fill=fill,
        )
    d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=fill)
    d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=fill)


def _draw_arc_ring(
    d: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r_in: float,
    r_out: float,
    deg_start: float,
    deg_end: float,
    fill: str,
) -> None:
    """Draw a smooth annular sector."""
    steps = 48
    a0 = math.radians(deg_start)
    a1 = math.radians(deg_end)
    pts_out = [
        (
            cx + r_out * math.cos(a0 + (a1 - a0) * i / steps),
            cy + r_out * math.sin(a0 + (a1 - a0) * i / steps),
        )
        for i in range(steps + 1)
    ]
    pts_in = [
        (
            cx + r_in * math.cos(a0 + (a1 - a0) * i / steps),
            cy + r_in * math.sin(a0 + (a1 - a0) * i / steps),
        )
        for i in range(steps + 1)
    ]
    d.polygon(pts_out + list(reversed(pts_in)), fill=fill)


def draw_icon() -> Image.Image:
    """Draw the 512px RGBA app icon."""
    s = SCALE
    image = Image.new("RGBA", (SIZE * s, SIZE * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    def box(x0: float, y0: float, x1: float, y1: float) -> list[float]:
        return [x0 * s, y0 * s, x1 * s, y1 * s]

    # 1. Dark navy rounded square background.
    d.rounded_rectangle(box(0, 0, SIZE - 1, SIZE - 1), radius=104 * s, fill=NAVY)

    # 2. Geometric cyan house pentagon.
    house_raw = [
        (228 * s, 78 * s),
        (392 * s, 212 * s),
        (392 * s, 404 * s),
        (64 * s, 404 * s),
        (64 * s, 212 * s),
    ]
    d.polygon(
        _rounded_polygon(house_raw, [20 * s, 24 * s, 24 * s, 24 * s, 24 * s]), fill=CYAN
    )

    # 3. Crisp white ESPHome-style serpentine circuit trace inside the house.
    trace_pts = [
        (140 * s, 392 * s),
        (140 * s, 198 * s),
        (264 * s, 198 * s),
        (264 * s, 242 * s),
        (188 * s, 242 * s),
        (188 * s, 286 * s),
        (256 * s, 286 * s),
        (256 * s, 330 * s),
        (188 * s, 330 * s),
        (188 * s, 374 * s),
        (244 * s, 374 * s),
    ]
    for i in range(len(trace_pts) - 1):
        _draw_thick_line(d, trace_pts[i], trace_pts[i + 1], width=22 * s, fill=WHITE)
    # Flush flat base at the bottom wall of the house.
    d.rectangle([129 * s, 384 * s, 151 * s, 404 * s], fill=WHITE)

    # 4. Golden wireless OTA signal arcs at the upper right of the roof.
    acx, acy = 336 * s, 166 * s
    for r_in, r_out, col in (
        (56 * s, 72 * s, YELLOW),
        (86 * s, 102 * s, GOLD),
    ):
        _draw_arc_ring(d, acx, acy, r_in, r_out, -72, 12, fill=col)

    # 5. Circular golden OTA upload badge at bottom-right with navy knockout ring.
    bcx, bcy = 356 * s, 348 * s
    d.ellipse([bcx - 96 * s, bcy - 96 * s, bcx + 96 * s, bcy + 96 * s], fill=NAVY)
    d.ellipse([bcx - 76 * s, bcy - 76 * s, bcx + 76 * s, bcy + 76 * s], fill=GOLD)

    # Crisp navy upward arrow inside the golden OTA badge.
    _draw_thick_line(
        d, (bcx, bcy + 40 * s), (bcx, bcy - 36 * s), width=22 * s, fill=NAVY
    )
    _draw_thick_line(
        d, (bcx - 36 * s, bcy - 4 * s), (bcx, bcy - 40 * s), width=22 * s, fill=NAVY
    )
    _draw_thick_line(
        d, (bcx + 36 * s, bcy - 4 * s), (bcx, bcy - 40 * s), width=22 * s, fill=NAVY
    )

    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    """Write icon.png, icon@2x.png, logo.png and logo@2x.png."""
    BRAND.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(BRAND / "icon@2x.png", optimize=True)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(
        BRAND / "icon.png", optimize=True
    )

    # Pillow bundles Aileron Regular, so regeneration needs no system fonts.
    font = ImageFont.load_default(size=272)
    bounds = font.getbbox("ESPHome OTA")
    wordmark = Image.new("RGBA", (bounds[2] - bounds[0], bounds[3] - bounds[1]))
    ImageDraw.Draw(wordmark).text(
        (-bounds[0], -bounds[1]), "ESPHome OTA", font=font, fill=WORDMARK
    )
    wordmark = wordmark.crop(wordmark.getbbox())
    gap = 96 + ((SIZE + 96 + wordmark.width) % 2)
    logo = Image.new("RGBA", (SIZE + gap + wordmark.width, SIZE))
    logo.alpha_composite(icon, (0, 0))
    logo.alpha_composite(wordmark, (SIZE + gap, (SIZE - wordmark.height) // 2))
    logo = logo.crop(logo.getbbox())
    logo.save(BRAND / "logo@2x.png", optimize=True)
    logo.resize((logo.width // 2, logo.height // 2), Image.Resampling.LANCZOS).save(
        BRAND / "logo.png", optimize=True
    )


if __name__ == "__main__":
    main()
