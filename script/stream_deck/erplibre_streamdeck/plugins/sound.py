# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sound page, SOUND home button and the microphone indicator.

Two polls read wpctl away from the lock: the Sound page's levels and
default devices into `state().audio`, every second while the page
shows, and the microphone's into `state().mic`, every 2 s while the
home screen shows. The page and the mic key draw only from those; a
press re-reads its levels itself, so the key shows its effect at
once. Each poll writes a failing wpctl once while it repeats."""

import re
import subprocess
import sys

from erplibre_streamdeck.plugin import (
    PLUGIN_API, Fixture, HomeButton, KeyFace, Page, Plugin, Poll,
    RepeatLog,
)
from erplibre_streamdeck.ui import colors, render

VOL_STEP_PCT = 5
WPCTL_SINK = "@DEFAULT_AUDIO_SINK@"
WPCTL_SOURCE = "@DEFAULT_AUDIO_SOURCE@"
# What the Sound page shows before its first poll: what a failing
# wpctl gives (sink volume, muted, source volume, muted, default sink
# and source short names).
NO_AUDIO = (None, None, None, None, "", "")
NO_MIC = (None, None)


def _log(msg):
    """Context.log's line, for the wpctl reads, which take no
    Context."""
    print(f"[erplibre-home] sound: {msg}", file=sys.stderr, flush=True)


def _wpctl_get(target, log=_log):
    """Return (volume_percent, muted) for target or (None, None) on
    error, which goes to log(msg)."""
    try:
        r = subprocess.run(
            ["wpctl", "get-volume", target],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode != 0:
            return None, None
        # Format: "Volume: 0.50" or "Volume: 0.50 [MUTED]"
        parts = r.stdout.strip().split()
        if len(parts) < 2:
            return None, None
        vol = float(parts[1])
        muted = len(parts) > 2 and "MUTED" in parts[2]
        return int(round(vol * 100)), muted
    except Exception as e:
        log(f"wpctl get-volume {target} error: {e}")
        return None, None


def _wpctl_volume_delta(target, delta_pct):
    sign = "+" if delta_pct > 0 else "-"
    try:
        r = subprocess.run(
            ["wpctl", "set-volume", "--limit", "1.5",
             target, f"{abs(delta_pct)}%{sign}"],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-volume error: {e}", file=sys.stderr, flush=True)
        return False


def _wpctl_mute_toggle(target):
    try:
        r = subprocess.run(
            ["wpctl", "set-mute", target, "toggle"],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-mute error: {e}", file=sys.stderr, flush=True)
        return False


_WPCTL_DEV_RE = re.compile(
    r"^\s*│\s+(\*\s+)?(\d+)\.\s+(.+?)\s+\[vol:"
)


def _wpctl_list_devices(kind):
    """Parse `wpctl status` for Audio Sinks or Sources.

    kind = 'Sinks' | 'Sources'. Returns list of
    {id: int, name: str, default: bool}, ordered as printed.
    """
    try:
        r = subprocess.run(
            ["wpctl", "status"],
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return []
    if r.returncode != 0:
        return []
    out = []
    in_audio = False
    in_section = False
    for line in r.stdout.splitlines():
        if line.startswith("Audio"):
            in_audio = True
            continue
        if line.startswith("Video"):
            in_audio = False
            continue
        if not in_audio:
            continue
        if f"├─ {kind}:" in line:
            in_section = True
            continue
        if line.startswith(" ├─") or line.startswith(" └─"):
            in_section = False
            continue
        if in_section:
            m = _WPCTL_DEV_RE.match(line)
            if m:
                marker, id_str, name = m.groups()
                out.append({
                    "id": int(id_str),
                    "name": name.strip(),
                    "default": bool(marker),
                })
    return out


def _wpctl_set_default(device_id):
    try:
        r = subprocess.run(
            ["wpctl", "set-default", str(device_id)],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except Exception as e:
        print(f"wpctl set-default error: {e}", file=sys.stderr, flush=True)
        return False


def _wpctl_cycle_default(kind):
    """Switch to the next device in the section. Returns new active dict."""
    devices = _wpctl_list_devices(kind)
    if not devices:
        return None
    idx = next(
        (i for i, d in enumerate(devices) if d["default"]),
        0,
    )
    nxt = devices[(idx + 1) % len(devices)]
    if _wpctl_set_default(nxt["id"]):
        return nxt
    return None


def _wpctl_default_short(kind):
    """Short label for the currently default device (last word, ≤ 6 chars)."""
    for d in _wpctl_list_devices(kind):
        if d["default"]:
            words = d["name"].split()
            tail = words[-1] if words else d["name"]
            return tail[:6]
    return ""


def _keys(geo):
    """Sound page keys. Needs >= 4 cols and >= 3 rows, else None. The
    SINK and SRC device pickers sit on row 0 next to BACK; they always
    exist once the deck is wide enough for the page."""
    if geo.cols < 4 or geo.rows < 3:
        return None
    return {
        "back": 0,
        "vol_down": geo.cols + 1,
        "vol_up": geo.cols + 2,
        "out_mute": geo.cols + 3,
        "mic_down": 2 * geo.cols + 1,
        "mic_up": 2 * geo.cols + 2,
        "mic_mute": 2 * geo.cols + 3,
        "sink": 1,    # row 0, col 1: cycles the default output
        "source": 2,  # row 0, col 2: cycles the default input
    }


def _read_audio(log=_log):
    """The Sound page's data, as NO_AUDIO orders it: no Context, no
    lock."""
    out_vol, out_muted = _wpctl_get(WPCTL_SINK, log)
    mic_vol, mic_muted = _wpctl_get(WPCTL_SOURCE, log)
    return (
        out_vol, out_muted, mic_vol, mic_muted,
        _wpctl_default_short("Sinks"), _wpctl_default_short("Sources"),
    )


def _read_mic(log=_log):
    """(volume, muted) of the default source."""
    return _wpctl_get(WPCTL_SOURCE, log)


# One per poll: a press reads with _log, from another thread.
_AUDIO_LOG = RepeatLog(_log, "Sound levels")
_MIC_LOG = RepeatLog(_log, "Mic level")


def _poll_audio():
    """The page poll's read (see RepeatLog)."""
    with _AUDIO_LOG.watch() as log:
        return _read_audio(log)


def _poll_mic():
    """The mic poll's read (see RepeatLog)."""
    with _MIC_LOG.watch() as log:
        return _read_mic(log)


def _keeper(name):
    """A poll's store: keeps the data as state().<name>; True when it
    differs from what was kept."""

    def store(ctx, data):
        st = ctx.state()
        changed = getattr(st, name, None) != data
        setattr(st, name, data)
        return changed

    return store


_store_audio = _keeper("audio")
_store_mic = _keeper("mic")


def _render(ctx):
    sk = ctx.keys
    if not sk:
        render.too_small(ctx)
        return

    (out_vol, out_muted, mic_vol, mic_muted, sink_short,
     source_short) = ctx.state().audio or NO_AUDIO

    labels = {
        sk["back"]: (colors.BACK, ctx.t("BACK")),
        sk["vol_down"]: (colors.VOL, f"VOL\n-{VOL_STEP_PCT}%"),
        sk["vol_up"]: (colors.VOL, f"VOL\n+{VOL_STEP_PCT}%"),
        sk["mic_down"]: (colors.MIC, f"MIC\n-{VOL_STEP_PCT}%"),
        sk["mic_up"]: (colors.MIC, f"MIC\n+{VOL_STEP_PCT}%"),
    }
    labels[sk["sink"]] = (colors.SOUND_TITLE, f"SINK\n{sink_short or '?'}")
    labels[sk["source"]] = (colors.MIC, f"SRC\n{source_short or '?'}")
    if out_muted:
        labels[sk["out_mute"]] = (colors.MUTE_ON, ctx.t("OUT\nMUTE"))
    else:
        out_lbl = f"OUT\n{out_vol}%" if out_vol is not None else "OUT"
        labels[sk["out_mute"]] = (colors.MUTE_OFF, out_lbl)
    if mic_muted:
        labels[sk["mic_mute"]] = (colors.MUTE_ON, ctx.t("MIC\nMUTE"))
    else:
        mic_lbl = f"MIC\n{mic_vol}%" if mic_vol is not None else "MIC"
        labels[sk["mic_mute"]] = (colors.MUTE_OFF, mic_lbl)

    for key in range(ctx.geo.total_keys):
        if key in labels:
            color, label = labels[key]
            ctx.set_key(key, color, label)
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _handle(ctx, key):
    sk = ctx.keys
    if not sk:
        # Unsupported deck size: any key returns home.
        ctx.home()
        return
    if key == sk["back"]:
        ctx.home()
        return
    if key == sk["vol_down"]:
        _wpctl_volume_delta(WPCTL_SINK, -VOL_STEP_PCT)
    elif key == sk["vol_up"]:
        _wpctl_volume_delta(WPCTL_SINK, VOL_STEP_PCT)
    elif key == sk["out_mute"]:
        _wpctl_mute_toggle(WPCTL_SINK)
    elif key == sk["mic_down"]:
        _wpctl_volume_delta(WPCTL_SOURCE, -VOL_STEP_PCT)
    elif key == sk["mic_up"]:
        _wpctl_volume_delta(WPCTL_SOURCE, VOL_STEP_PCT)
    elif key == sk["mic_mute"]:
        _wpctl_mute_toggle(WPCTL_SOURCE)
    elif key == sk.get("sink"):
        _wpctl_cycle_default("Sinks")
    elif key == sk.get("source"):
        _wpctl_cycle_default("Sources")
    else:
        return
    audio = _read_audio()
    _store_audio(ctx, audio)
    # The source read also feeds the mic key: back home, it shows a
    # mute made on this page at once.
    _store_mic(ctx, audio[2:4])
    ctx.render()


def _mic_place(geo, home_keys):
    """The microphone key: first column of the last row."""
    return [(geo.rows - 1) * geo.cols] if geo.rows >= 2 else []


def _mic_face(ctx, key, index):
    """The mic status icon follows the mute state, not the translated
    label, so a translated OFF still picks the muted icon."""
    vol, muted = ctx.state().mic or NO_MIC
    if vol is None:
        return KeyFace(colors.BT_NA, ctx.t("MIC\nN/A"))
    if muted:
        return KeyFace(colors.MUTE_ON, ctx.t("MIC\nOFF"), icon="mic_off")
    return KeyFace(colors.MUTE_OFF, ctx.t("MIC\nON"), icon="mic_on")


def _mic_press(ctx, key, index):
    _wpctl_mute_toggle(WPCTL_SOURCE)
    _store_mic(ctx, _read_mic())
    ctx.render()


def _setup(ctx):
    st = ctx.state()
    st.audio = None
    st.mic = None


def _page_shown(ctx):
    """The Sound page shows at a size that draws its levels."""
    return ctx.page == "sound" and bool(ctx.keys)


def _mic_shown(ctx):
    """The home screen ("idle") shows and the mic key has its place.
    Its fixture has the lowest order and its key is on the last row,
    below every home button, so the place it asks for is the key it
    gets."""
    return ctx.page == "idle" and bool(_mic_place(ctx.geo, ctx.home_keys))


PLUGIN = Plugin(
    api=PLUGIN_API,
    pages=[Page("sound", _keys, _render, _handle)],
    home_button=HomeButton(
        40,
        face=lambda ctx: KeyFace(
            colors.SOUND_TITLE, ctx.t("SOUND"), icon="sound"
        ),
        press=lambda ctx: ctx.goto("sound"),
    ),
    fixtures=[Fixture(10, _mic_place, _mic_face, _mic_press)],
    polls=[
        Poll(1.0, _page_shown, _poll_audio, _store_audio),
        Poll(2.0, _mic_shown, _poll_mic, _store_mic),
    ],
    setup=_setup,
)
