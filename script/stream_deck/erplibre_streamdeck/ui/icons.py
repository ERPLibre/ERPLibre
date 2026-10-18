# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Icon painters of the deck keys. A painter takes (draw, w, h) and draws
in the key's pixel box; ICONS maps a name to its painter."""

from erplibre_streamdeck.ui import colors


def icon_mic(draw, w, h, muted=False):
    cx = w / 2
    cap_w = w * 0.30
    cap_h = h * 0.42
    cap_box = (cx - cap_w / 2, h * 0.18, cx + cap_w / 2, h * 0.18 + cap_h)
    draw.rounded_rectangle(cap_box, radius=cap_w / 2, fill=colors.ICON_WHITE)
    stroke = max(2, int(w * 0.05))
    draw.line(
        (cx, h * 0.62, cx, h * 0.78),
        fill=colors.ICON_WHITE, width=stroke,
    )
    arc_box = (w * 0.25, h * 0.50, w * 0.75, h * 0.78)
    draw.arc(arc_box, 0, 180, fill=colors.ICON_WHITE, width=stroke)
    draw.line(
        (w * 0.32, h * 0.78, w * 0.68, h * 0.78),
        fill=colors.ICON_WHITE, width=stroke,
    )
    if muted:
        draw.line(
            (w * 0.15, h * 0.85, w * 0.85, h * 0.15),
            fill=colors.ICON_RED, width=max(3, int(w * 0.08)),
        )


def icon_mic_off(draw, w, h):
    icon_mic(draw, w, h, muted=True)


def icon_tile(draw, w, h):
    cells = [(0.18, 0.18), (0.55, 0.18), (0.18, 0.55), (0.55, 0.55)]
    cw = w * 0.27
    for x, y in cells:
        draw.rectangle(
            (w * x, h * y, w * x + cw, h * y + cw),
            fill=colors.ICON_WHITE,
        )


def icon_timer(draw, w, h):
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.36
    box = (cx - r, cy - r, cx + r, cy + r)
    stroke = max(2, int(w * 0.05))
    draw.ellipse(box, outline=colors.ICON_WHITE, width=stroke)
    draw.line((cx, cy, cx, cy - r * 0.7), fill=colors.ICON_WHITE, width=stroke)
    draw.line((cx, cy, cx + r * 0.5, cy), fill=colors.ICON_WHITE, width=stroke)
    # Top stub knob
    knob = w * 0.06
    draw.rectangle(
        (cx - knob, cy - r - knob, cx + knob, cy - r),
        fill=colors.ICON_WHITE,
    )


def icon_dev_reload(draw, w, h):
    cx, cy = w / 2, h / 2
    r = min(w, h) * 0.34
    box = (cx - r, cy - r, cx + r, cy + r)
    stroke = max(3, int(w * 0.07))
    # Arc ~300° leaving a gap top-right for the arrowhead
    draw.arc(box, 30, 320, fill=colors.ICON_WHITE, width=stroke)
    # Arrowhead at the end of the arc (top-right area, angle 30°)
    import math
    a = math.radians(30)
    tip = (cx + r * math.cos(a), cy + r * math.sin(a))
    size = w * 0.13
    draw.polygon(
        [
            (tip[0] + size, tip[1] - size * 0.2),
            (tip[0] - size * 0.2, tip[1] + size),
            (tip[0] - size * 0.4, tip[1] - size * 0.4),
        ],
        fill=colors.ICON_WHITE,
    )


def icon_sound(draw, w, h):
    cy = h / 2
    # Speaker body: rect + triangle horn
    body_x0 = w * 0.20
    body_x1 = w * 0.36
    body_y0 = cy - h * 0.13
    body_y1 = cy + h * 0.13
    draw.rectangle(
        (body_x0, body_y0, body_x1, body_y1), fill=colors.ICON_WHITE
    )
    horn = [
        (body_x1, body_y0),
        (w * 0.55, h * 0.20),
        (w * 0.55, h * 0.80),
        (body_x1, body_y1),
    ]
    draw.polygon(horn, fill=colors.ICON_WHITE)
    stroke = max(2, int(w * 0.05))
    # Two sound waves
    for ofs, size in ((0.02, 0.20), (0.10, 0.32)):
        rb = (
            w * (0.55 + ofs),
            cy - h * size,
            w * (0.55 + ofs) + h * size * 2,
            cy + h * size,
        )
        draw.arc(rb, -45, 45, fill=colors.ICON_WHITE, width=stroke)


def icon_layout(draw, w, h):
    stroke = max(2, int(w * 0.06))
    # Outer frame
    draw.rectangle(
        (w * 0.15, h * 0.20, w * 0.85, h * 0.80),
        outline=colors.ICON_WHITE, width=stroke,
    )
    # Sidebar split
    draw.line(
        (w * 0.40, h * 0.20, w * 0.40, h * 0.80),
        fill=colors.ICON_WHITE, width=stroke,
    )
    # Title bar
    draw.line(
        (w * 0.40, h * 0.36, w * 0.85, h * 0.36),
        fill=colors.ICON_WHITE, width=stroke,
    )


def icon_a11y(draw, w, h):
    cx = w / 2
    # Head
    head_r = w * 0.10
    draw.ellipse(
        (cx - head_r, h * 0.14, cx + head_r, h * 0.14 + head_r * 2),
        fill=colors.ICON_WHITE,
    )
    stroke = max(2, int(w * 0.06))
    # Arms outstretched
    draw.line(
        (w * 0.20, h * 0.45, w * 0.80, h * 0.45),
        fill=colors.ICON_WHITE, width=stroke,
    )
    # Body trunk
    draw.line(
        (cx, h * 0.40, cx, h * 0.65),
        fill=colors.ICON_WHITE, width=stroke,
    )
    # Legs
    draw.line(
        (cx, h * 0.65, w * 0.32, h * 0.85),
        fill=colors.ICON_WHITE, width=stroke,
    )
    draw.line(
        (cx, h * 0.65, w * 0.68, h * 0.85),
        fill=colors.ICON_WHITE, width=stroke,
    )


def icon_translator(draw, w, h):
    # Speech bubble with tail + 3 dots inside
    stroke = max(2, int(w * 0.05))
    box = (w * 0.15, h * 0.18, w * 0.85, h * 0.62)
    draw.rounded_rectangle(
        box, radius=h * 0.10, outline=colors.ICON_WHITE, width=stroke,
    )
    # Tail
    tail = [
        (w * 0.30, h * 0.62),
        (w * 0.25, h * 0.85),
        (w * 0.45, h * 0.62),
    ]
    draw.polygon(tail, fill=colors.ICON_WHITE)
    # Three dots inside
    cy = h * 0.40
    r = w * 0.05
    for cx in (w * 0.32, w * 0.50, w * 0.68):
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r), fill=colors.ICON_WHITE,
        )


def icon_bt(draw, w, h):
    stroke = max(3, int(w * 0.07))
    cx = w / 2
    points = [
        (cx, h * 0.15),
        (w * 0.70, h * 0.35),
        (w * 0.30, h * 0.65),
        (w * 0.70, h * 0.65),
        (cx, h * 0.85),
        (cx, h * 0.15),
        (w * 0.30, h * 0.35),
        (w * 0.70, h * 0.65),
    ]
    draw.line(points, fill=colors.ICON_WHITE, width=stroke, joint="curve")


def icon_robot(draw, w, h):
    stroke = max(2, int(w * 0.05))
    # Antenna
    cx = w / 2
    draw.line([(cx, h * 0.10), (cx, h * 0.22)],
              fill=colors.ICON_WHITE, width=stroke)
    draw.ellipse(
        [cx - w * 0.05, h * 0.05, cx + w * 0.05, h * 0.15],
        fill=colors.ICON_WHITE,
    )
    # Head
    draw.rounded_rectangle(
        [w * 0.20, h * 0.25, w * 0.80, h * 0.65],
        radius=int(w * 0.10), outline=colors.ICON_WHITE, width=stroke,
    )
    # Eyes
    eye_r = max(2, int(w * 0.05))
    draw.ellipse(
        [w * 0.32 - eye_r, h * 0.42 - eye_r,
         w * 0.32 + eye_r, h * 0.42 + eye_r],
        fill=colors.ICON_WHITE,
    )
    draw.ellipse(
        [w * 0.68 - eye_r, h * 0.42 - eye_r,
         w * 0.68 + eye_r, h * 0.42 + eye_r],
        fill=colors.ICON_WHITE,
    )
    # Mouth
    draw.line(
        [(w * 0.36, h * 0.55), (w * 0.64, h * 0.55)],
        fill=colors.ICON_WHITE, width=stroke,
    )
    # Body hint (shoulders)
    draw.line(
        [(w * 0.30, h * 0.72), (w * 0.70, h * 0.72)],
        fill=colors.ICON_WHITE, width=stroke,
    )


ICONS = {
    "mic_on": icon_mic,
    "mic_off": icon_mic_off,
    "tile": icon_tile,
    "timer": icon_timer,
    "dev_reload": icon_dev_reload,
    "sound": icon_sound,
    "layout": icon_layout,
    "a11y": icon_a11y,
    "bt": icon_bt,
    "translator": icon_translator,
    "robot": icon_robot,
}
