# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Translator pages: speech-to-text recording, LLM post-processing,
the streaming translator and the history of transcriptions.

The `translator` module does the work; this plugin keeps the choices
(STT backend, output method, LLM mode and backend) in its state and in
settings.json. A recording is transcribed on a worker thread, which
takes the kernel lock only to record the flash and redraw."""

import os
import subprocess
import sys
import tempfile
import threading
import time

import translator

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Page, Plugin,
)
from erplibre_streamdeck.ui import colors, render

MAIN = "translator"
HISTORY = "translator_history"


def _keys(geo):
    """Translator page keys. Requires >= 4 cols and >= 2 rows, else
    None. LLM controls appear when there is room (cols >= 6), the
    history key from 7 columns."""
    if geo.cols < 4 or geo.rows < 2:
        return None
    keys = {
        "back": 0,
        "stream": geo.cols + 0,
        "record": geo.cols + 1,
        "backend": geo.cols + 2,
        "output": geo.cols + 3,
    }
    if geo.cols >= 6:
        keys["llm_mode"] = geo.cols + 4
        keys["llm_backend"] = geo.cols + 5
    if geo.cols >= 7:
        keys["history"] = geo.cols + 6
    return keys


def _setup(ctx):
    """Detect the backends (the LLM probe opens local ports with a
    1 s timeout each) and restore the last selections."""
    st = ctx.state()
    st.stt_backends = translator.detect_stt_backends()
    st.stt_index = 0
    st.output_methods = (
        translator.detect_output_methods()
        or [translator.OUTPUT_CLIP]
    )
    st.output_index = 0
    st.llm_backends = translator.detect_llm_backends()
    st.llm_index = 0
    st.llm_mode_index = 0  # off / translate / chat
    st.record_proc = None
    st.record_path = None
    st.record_started_at = 0.0
    st.vad_should_stop = False
    st.streaming_proc = None
    prefs = ctx.settings.load()
    if prefs.get("translator_stt"):
        for i, b in enumerate(st.stt_backends):
            if b.name == prefs["translator_stt"]:
                st.stt_index = i
                break
    if prefs.get("translator_output") in st.output_methods:
        st.output_index = st.output_methods.index(
            prefs["translator_output"]
        )
    if prefs.get("translator_llm"):
        for i, b in enumerate(st.llm_backends):
            if b.name == prefs["translator_llm"]:
                st.llm_index = i
                break
    if prefs.get("translator_llm_mode") in translator.LLM_MODES:
        st.llm_mode_index = translator.LLM_MODES.index(
            prefs["translator_llm_mode"]
        )


def _save_pref(ctx, key, value):
    """Read settings.json again right before writing it, so the keys
    other plugins wrote since start survive."""
    data = ctx.settings.load()
    data[key] = value
    ctx.settings.save(data)


def _stop_streaming(proc):
    """terminate, wait 2 s, kill when either step raises."""
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _handle(ctx, key):
    st = ctx.state()
    tk = ctx.keys
    if not tk:
        ctx.home()
        return
    if key == tk["back"]:
        # The recorder stops without a transcription; record_path and
        # its WAV file stay as they are.
        if st.record_proc is not None:
            translator.stop_recording(st.record_proc)
            st.record_proc = None
        ctx.home()
        return
    if key == tk["record"]:
        _toggle_record(ctx)
        return
    if key == tk["backend"] and st.stt_backends:
        st.stt_index = (st.stt_index + 1) % len(st.stt_backends)
        _save_pref(
            ctx, "translator_stt", st.stt_backends[st.stt_index].name
        )
        ctx.render()
        return
    if key == tk["output"]:
        st.output_index = (st.output_index + 1) % len(st.output_methods)
        _save_pref(
            ctx, "translator_output", st.output_methods[st.output_index]
        )
        ctx.render()
        return
    if key == tk.get("llm_mode"):
        st.llm_mode_index = (
            (st.llm_mode_index + 1) % len(translator.LLM_MODES)
        )
        _save_pref(
            ctx, "translator_llm_mode",
            translator.LLM_MODES[st.llm_mode_index],
        )
        ctx.render()
        return
    if key == tk.get("llm_backend") and st.llm_backends:
        st.llm_index = (st.llm_index + 1) % len(st.llm_backends)
        _save_pref(
            ctx, "translator_llm", st.llm_backends[st.llm_index].name
        )
        ctx.render()
        return
    if key == tk.get("history"):
        ctx.goto(HISTORY)
        return
    if key == tk.get("stream"):
        _toggle_streaming(ctx)
        return


def _handle_history(ctx, key):
    # Layout: 0 = BACK, total-1 = CLEAR, others map to entries.
    st = ctx.state()
    total = ctx.geo.total_keys
    if key == 0:
        ctx.goto(MAIN)
        return
    if key == total - 1:
        translator.clear_history()
        ctx.render()
        return
    # The file is read again: an entry appended since the render
    # shifts the slots.
    entries = list(reversed(translator.load_history()))
    # Slot map: keys 1..total-2 map to entries[0..]
    idx = key - 1
    if 0 <= idx < len(entries):
        entry = entries[idx]
        method = st.output_methods[st.output_index]
        ok = translator.output_text(entry.get("text", ""), method)
        ctx.flash(ok)
        ctx.render()


def _toggle_streaming(ctx):
    st = ctx.state()
    if st.streaming_proc is not None and (
            st.streaming_proc.poll() is None):
        _stop_streaming(st.streaming_proc)
        st.streaming_proc = None
        ctx.render()
        return
    script = os.fspath(paths.STREAM_DECK_DIR / "translator_stream.py")
    try:
        st.streaming_proc = subprocess.Popen(
            [sys.executable, script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        st.streaming_proc = None
        ctx.flash(False, f"streaming start failed: {e}")
    ctx.render()


def _toggle_record(ctx):
    st = ctx.state()
    if st.record_proc is None:
        if not st.stt_backends:
            ctx.flash(
                False,
                "translator: no STT backend available "
                "(install whisper-cpp or vosk)",
            )
            ctx.render()
            return
        fd, path = tempfile.mkstemp(prefix="sttrec_", suffix=".wav")
        os.close(fd)
        st.record_path = path
        st.vad_should_stop = False
        if translator.vad_enabled():
            # on_silence runs on the recorder's stderr reader thread:
            # it only sets the flag the page tick reads.
            st.record_proc = translator.start_recording_vad(
                path,
                on_silence=lambda: setattr(st, "vad_should_stop", True),
            )
        else:
            st.record_proc = translator.start_recording(path)
        if st.record_proc is None:
            ctx.flash(
                False, f"translator: failed to start recording at {path}"
            )
            os.unlink(path)
            st.record_path = None
        else:
            st.record_started_at = time.monotonic()
        ctx.render()
        return
    # Stop + transcribe
    translator.stop_recording(st.record_proc)
    st.record_proc = None
    st.record_started_at = 0.0
    path = st.record_path
    st.record_path = None
    ctx.render()
    threading.Thread(
        target=_finish_transcription,
        args=(ctx, path),
        daemon=True,
    ).start()


def _finish_transcription(ctx, wav_path):
    """Worker thread: transcribe, post-process, output, append to the
    history, then flash under the kernel lock. An exception from the
    backend or the output ends the thread before the flash."""
    st = ctx.state()
    ok = False
    try:
        backend = st.stt_backends[st.stt_index]
        raw = backend.transcribe(wav_path)
        llm_mode = translator.LLM_MODES[st.llm_mode_index]
        llm_backend = (
            st.llm_backends[st.llm_index] if st.llm_backends else None
        )
        text = translator.llm_postprocess(raw, llm_mode, llm_backend)
        if text:
            method = st.output_methods[st.output_index]
            ok = translator.output_text(text, method)
            try:
                translator.append_history(
                    text,
                    llm_mode=llm_mode,
                    language=translator.stt_language(),
                    wm_class=translator.focused_window_class(),
                )
            except Exception as e:
                print(
                    f"history append error: {e}",
                    file=sys.stderr, flush=True,
                )
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass
    with ctx.locked():
        ctx.flash(ok)
        if ctx.page == MAIN:
            ctx.render()


def _tick(ctx, now):
    """While recording: stop on the voice-detection flag, else once
    the recording timeout has elapsed."""
    st = ctx.state()
    if st.record_proc is None or st.record_started_at <= 0:
        return
    if st.vad_should_stop:
        st.vad_should_stop = False
        _toggle_record(ctx)
        return
    timeout = translator.recording_timeout_seconds()
    elapsed = now - st.record_started_at
    if timeout > 0 and elapsed >= timeout:
        _toggle_record(ctx)


def _render_history(ctx):
    total = ctx.geo.total_keys
    entries = list(reversed(translator.load_history()))
    for key in range(total):
        if key == 0:
            ctx.set_key(key, colors.BACK, ctx.t("BACK"))
            continue
        if key == total - 1:
            ctx.set_key(key, colors.CANCEL, ctx.t("CLEAR"))
            continue
        idx = key - 1
        if idx < len(entries):
            text = entries[idx].get("text") or ""
            snippet = text[:8] if len(text) > 8 else text
            ctx.set_key(key, colors.LOAD_FILLED, snippet)
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _render(ctx):
    st = ctx.state()
    tk = ctx.keys
    if not tk:
        render.too_small(ctx)
        return
    recording = st.record_proc is not None
    if st.stt_backends:
        backend_name = st.stt_backends[st.stt_index].name
    else:
        backend_name = "NONE"
    method = st.output_methods[st.output_index]
    method_lbl = "TYPE" if method == translator.OUTPUT_TYPE else "CLIP"
    rec_color = colors.REC_ON if recording else colors.REC_OFF
    rec_label = "STOP" if recording else "REC"
    rec_icon = "mic_on" if recording else "mic_off"
    llm_mode = translator.LLM_MODES[st.llm_mode_index]
    llm_lbl = {
        translator.LLM_MODE_OFF: "LLM\nOFF",
        translator.LLM_MODE_TRANSLATE: "LLM\nTRSL",
        translator.LLM_MODE_CHAT: "LLM\nCHAT",
    }[llm_mode]
    llm_color = (
        colors.LLM_OFF if llm_mode == translator.LLM_MODE_OFF
        else colors.LLM_ON
    )
    if st.llm_backends:
        llm_be_name = st.llm_backends[st.llm_index].name[:6]
    else:
        llm_be_name = "NONE"
    assignments = {
        tk["back"]: (colors.BACK, ctx.t("BACK"), None),
        tk["record"]: (rec_color, rec_label, rec_icon),
        tk["backend"]: (
            colors.BACKEND, f"STT\n{backend_name[:6]}", None,
        ),
        tk["output"]: (colors.OUTPUT, f"OUT\n{method_lbl}", None),
    }
    if "llm_mode" in tk:
        assignments[tk["llm_mode"]] = (llm_color, llm_lbl, None)
    if "llm_backend" in tk:
        assignments[tk["llm_backend"]] = (
            colors.BACKEND, f"LLM\n{llm_be_name}", None,
        )
    streaming_active = (
        st.streaming_proc is not None
        and st.streaming_proc.poll() is None
    )
    if "stream" in tk:
        stream_color = colors.REC_ON if streaming_active else colors.VOL
        stream_lbl = "STR\nON" if streaming_active else "STR"
        assignments[tk["stream"]] = (stream_color, stream_lbl, None)
    for key in range(ctx.geo.total_keys):
        if key in assignments:
            color, label, icon = assignments[key]
            ctx.set_key(key, color, label, icon=icon)
        else:
            ctx.set_key(key, colors.EMPTY, "")


def _shutdown(ctx):
    """Stop the streaming translator, and a recording in progress
    without a transcription: its WAV file is removed. The process may
    outlive this kernel (an unplugged deck), and no tick or key of the
    next one reaches these children. Runs with the kernel lock held: no
    lock, no join; each stop waits a few seconds at most."""
    st = ctx.state()
    if st.streaming_proc is not None:
        _stop_streaming(st.streaming_proc)
    if st.record_proc is not None:
        translator.stop_recording(st.record_proc)
        st.record_proc = None
    if st.record_path is not None:
        try:
            os.unlink(st.record_path)
        except OSError:
            pass
        st.record_path = None


PLUGIN = Plugin(
    api=PLUGIN_API,
    setup=_setup,
    shutdown=_shutdown,
    pages=[
        Page(MAIN, _keys, _render, _handle, tick=_tick, period=0.0),
        Page(HISTORY, None, _render_history, _handle_history),
    ],
    home_button=HomeButton(
        80,
        face=lambda ctx: KeyFace(
            colors.TR_TITLE, ctx.t("TRANSL"), icon="translator"
        ),
        press=lambda ctx: ctx.goto(MAIN),
    ),
)
