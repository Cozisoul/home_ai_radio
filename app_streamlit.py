#!/usr/bin/env python3
"""
app_streamlit.py – Streamlit front-end for Research Radio.
Controls: Play, Pause, Next, Previous, Mood, Voice select, and Test.
"""

import streamlit as st
from pathlib import Path
import threading
import time

from random_radio_ollama import (
    RandomRadio, build_albums, DEFAULT_OLLAMA_MODEL, ROOT_ALBUMS
)

# ---------------------- Startup ----------------------
st.set_page_config(page_title="Research Radio", page_icon="📻", layout="centered")

# Resolve albums root
ROOT = Path("/Volumes/Elements/Old Laptop/Disc D/albums")
ALBUMS_ROOT = ROOT if ROOT.is_dir() else (ROOT_ALBUMS if ROOT_ALBUMS.is_dir() else Path("./albums"))

# Singleton radio instance across reruns
@st.cache_resource
def get_radio():
    albums = build_albums(ALBUMS_ROOT)
    radio = RandomRadio(
        albums,
        endless=True,
        export_csv=Path("history.csv"),
        model=DEFAULT_OLLAMA_MODEL,
        duck_to=20,
        music_vol=90,
        fx_dir=Path("./fx"),
        voice_match=None,   # user can pick later
    )
    # start in background thread
    def _run():
        radio.start()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return radio

radio = get_radio()

st.title("📻 Research Radio — Host Mode (Smooth + Laidback)")

# ---------------------- Controls ----------------------
with st.sidebar:
    st.header("Transport")
    colA, colB, colC, colD = st.columns(4)
    if colA.button("⏮ Prev"):
        radio.previous()
    if colB.button("⏯ Pause"):
        radio.pause()
    if colC.button("▶ Play"):
        radio.play()
    if colD.button("⏭ Next"):
        radio.skip()

    st.markdown("---")
    st.header("Mood")
    mood = st.text_input("Set mood for next selection (e.g., 'downtempo haze', 'golden-hour hip-hop')", value="")
    c1, c2 = st.columns(2)
    if c1.button("Set Mood"):
        radio.set_mood_hint(mood or None)
        st.success(f"Mood set: {mood or 'cleared'}")
    if c2.button("Clear Mood"):
        radio.set_mood_hint(None)
        st.info("Mood cleared")

    st.markdown("---")
    st.header("Voice")
    if st.button("Refresh Voices"):
        st.experimental_rerun()
    voices = radio.list_voices()
    vnames = [f"{i}: {v.get('name')} | {v.get('id')}" for i, v in enumerate(voices)]
    chosen = st.selectbox("Choose a TTS voice (by substring match)", vnames if vnames else ["No voices found"])
    voice_query = st.text_input("Or type a custom match (e.g., 'en_US' / 'Zira' / 'Daniel')", value="")
    if st.button("Apply Voice"):
        match = (voice_query or chosen.split("|")[-1]).strip()
        selected = radio.set_voice(match)
        if selected:
            st.success(f"Voice set: {selected}")
        else:
            st.warning("No voice matched that query.")

    st.markdown("---")
    st.header("Quick Commands")
    cmd = st.text_input("Command (skip / previous / play / pause / mood <text> / voice <match> / now)")
    if st.button("Send"):
        res = radio.perform_command(cmd)
        st.write(res)

# ---------------------- Main ----------------------
st.subheader("Now Playing")
info = radio.current_track_info()
st.write(f"**{info['album']} – {info['track']}**")

st.subheader("Recent History")
hist = radio.history[-12:][::-1]
if not hist:
    st.info("No history yet—starting soon...")
else:
    for e in hist:
        st.write(f"{e['timestamp']} → {e['album']} – {e['track']}")

# ---------------------- Test Panel ----------------------
with st.expander("Diagnostics / Test"):
    col1, col2 = st.columns(2)
    if col1.button("Speak Test Line (duck)"):
        # simple on-air ID
        radio._speak_over_music("Research Radio ID: Broadcasting on the inside channel. Stay tuned.")
        st.success("Spoken.")
    if col2.button("Play FX: Rewind"):
        radio.play_fx("rewind")
        st.success("FX played (if file exists).")

    st.write("Albums root:", str(ALBUMS_ROOT))
    st.write("Tracks in queue:", len(getattr(radio, "queue", [])))
    st.write("Voices available:", len(voices) if voices else 0)
    st.caption("Tip: put small FX files in ./fx named like 'airhorn.wav' or 'rewind.mp3'.")

# Gentle heartbeat to keep UI fresh
time.sleep(0.05)