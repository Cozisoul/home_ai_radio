# ------------------------------------------------------------------
#  radio_app.py
#  Streamlit front‑end for the RandomRadio DJ
# ------------------------------------------------------------------
import sys
import os
import threading
import streamlit as st
from pathlib import Path
import pandas as pd

# ------------------------------------------------------------------
#  Make the DJ module importable
# ------------------------------------------------------------------
# Adjust the path so that Streamlit can find the DJ code.
# Put the DJ script in the same folder as this app
# or change the path to the folder that contains it.
DJ_DIR = Path(__file__).parent
sys.path.append(str(DJ_DIR))

try:
    from random_radio_ollama import RandomRadio, discover_albums
except Exception as exc:
    st.error(f"Could not import DJ code: {exc}")
    sys.exit(1)

# ------------------------------------------------------------------
#  Streamlit helpers
# ------------------------------------------------------------------
def _ensure_radio():
    """Lazy‑create a Radio instance in session_state if it does not exist."""
    if "radio" not in st.session_state:
        st.session_state.radio = None
    if "thread" not in st.session_state:
        st.session_state.thread = None


def _start_radio():
    """Start the DJ in a background thread."""
    _ensure_radio()
    if st.session_state.radio is None:
        root = Path(st.session_state.root_path).expanduser()
        if not root.exists():
            st.error(f"Root directory does not exist: {root}")
            return
        albums = discover_albums(root)
        if not albums:
            st.warning("No audio files found in the selected root.")
            return

        st.session_state.radio = RandomRadio(
            albums=albums,
            export_csv=Path(st.session_state.csv_path) if st.session_state.csv_path else None,
            fx_dir=Path(st.session_state.fx_dir) if st.session_state.fx_dir else None,
            duck_to=st.session_state.duck,
            music_vol=st.session_state.music,
        )
        st.session_state.thread = threading.Thread(
            target=st.session_state.radio.start, daemon=True
        )
        st.session_state.thread.start()
        st.success("Radio started – you should now hear music on your speakers!")


def _stop_radio():
    """Stop the DJ."""
    if st.session_state.radio:
        st.session_state.radio.player.stop()
        st.session_state.radio = None
        st.session_state.thread = None
        st.success("Radio stopped.")


# ------------------------------------------------------------------
#  Streamlit layout
# ------------------------------------------------------------------
def main():
    st.set_page_config(page_title="AI Radio Control", layout="wide")

    st.title("🌀 AI Radio Control Panel")

    # ---------- Sidebar: configuration ----------
    with st.sidebar:
        st.header("Configuration")
        st.text_input(
            label="Root folder containing music",
            value=str(Path.home()),
            key="root_path",
            help="Full path – wrap it in quotes if it contains spaces",
        )
        st.text_input(
            label="CSV log file (optional)",
            value="",
            key="csv_path",
            help="Full path to a CSV file that will be appended to",
        )
        st.text_input(
            label="FX folder (optional)",
            value="",
            key="fx_dir",
            help="Folder containing short FX files (airhorn.wav etc.)",
        )
        st.slider(
            "Duck volume (%)",
            min_value=0,
            max_value=100,
            value=20,
            key="duck",
        )
        st.slider(
            "Music volume (%)",
            min_value=0,
            max_value=100,
            value=80,
            key="music",
        )
        st.markdown("---")
        if st.button("Start Radio"):
            _start_radio()
        if st.button("Stop Radio"):
            _stop_radio()

    # ---------- Main panel ----------
    if st.session_state.get("radio") is None:
        st.info("Please press **Start Radio** in the sidebar to begin.")
        return

    radio = st.session_state.radio

    # ---- Current track information ----
    st.subheader("Now Playing")
    album, track_path = radio.current_track()
    st.write(f"**Album:** {album}")
    st.write(f"**Track:** {track_path.name}")

    # ---- Commentary display ----
    if radio.history:
        last_commentary = radio.history[-1]["commentary"]
        st.subheader("Latest Commentary")
        st.text_area("Commentary", value=last_commentary, height=120, key="commentary_area")

    # ---- Playback controls ----
    st.markdown("---")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("⏮️ Previous", key="prev_btn"):
            radio.idx = (radio.idx - 1) % len(radio.queue)
            radio._play_current()

    with col2:
        if st.button("⏸️ Pause/Play", key="pause_btn"):
            if radio.player.is_playing():
                radio.player.pause()
            else:
                radio.player.play()

    with col3:
        if st.button("⏭️ Next", key="next_btn"):
            radio.idx = (radio.idx + 1) % len(radio.queue)
            radio._play_current()

    # ---- Volume sliders (live) ----
    st.markdown("---")
    col4, col5 = st.columns(2)

    with col4:
        duck = st.slider(
            "Duck Volume",
            min_value=0,
            max_value=100,
            value=radio.duck_to,
            key="duck_slider",
            on_change=lambda d=radio.duck_to: setattr(radio, "duck_to", d),
        )
        radio.duck_to = duck

    with col5:
        music = st.slider(
            "Music Volume",
            min_value=0,
            max_value=100,
            value=radio.music_vol,
            key="music_slider",
            on_change=lambda m=radio.music_vol: radio.player.audio_set_volume(m),
        )
        radio.music_vol = music

    # ---- Recent history table ----
    st.markdown("---")
    st.subheader("Recent Tracks / Commentaries")
    if radio.history:
        df = pd.DataFrame(radio.history)
        # Show only the 10 most recent rows
        st.dataframe(df.tail(10).reset_index(drop=True))
    else:
        st.write("No history yet – you’re listening to the first track.")


if __name__ == "__main__":
    main()
