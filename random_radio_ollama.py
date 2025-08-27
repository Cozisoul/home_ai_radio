#!/usr/bin/env python3
"""
random_radio_ollama.py
~~~~~~~~~~~~~~~~~~~~~~
Random Radio with:
• Shuffled library
• Local Ollama “DJ host” commentary
• Duck‑ing & FX stingers
• CSV/MySQL history logging
• Voice‑selection TTS
• Mood‑guided next‑track selection
"""

from __future__ import annotations

import sys
import argparse
import pathlib
import random
import logging
import time
import csv
import threading
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse

# ------------------------------------------------------------------ #
# Dependencies
# ------------------------------------------------------------------ #
try:
    import vlc  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "python‑vlc (and the underlying libvlc) is required. "
        "Install it with `pip install python-vlc` and make sure libvlc is "
        "available in your system path."
    ) from exc

try:
    from ollama import Client  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "ollama Python client is required. Install it with "
        "`pip install ollama`."
    ) from exc

try:
    import pyttsx3  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "pyttsx3 (text‑to‑speech) is required. Install it with "
        "`pip install pyttsx3`."
    ) from exc

# Optional – only used if you want voice‑recognition later
try:
    import speech_recognition as sr  # type: ignore
except Exception:  # pragma: no cover
    sr = None

# ------------------------------------------------------------------ #
# Configuration
# ------------------------------------------------------------------ #
ROOT_ALBUMS = pathlib.Path("/Volumes/Elements/Old Laptop/Disc D/albums")
SUPPORTED_EXT = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg"}
LOG_LEVEL = logging.INFO
DEFAULT_OLLAMA_MODEL = "gemma3:4b"

# Ducking
DEFAULT_DUCK_TO = 20          # % volume while talking
DEFAULT_MUSIC_VOL = 90        # % volume while playing
DEFAULT_TALK_RATE = 145
DEFAULT_TALK_VOL = 0.95

# FX
DEFAULT_FX_DIR = pathlib.Path("./fx")

# ------------------------------------------------------------------ #
# Logging
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def _load_context() -> str:
    """Read the first 200 bytes of the README that ships next to this file."""
    try:
        readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
        if readme.is_file():
            return readme.read_text(encoding="utf-8")[:200]
    except Exception:  # pragma: no cover
        pass
    return ""

SYSTEM_PROMPT = f"""
You are the voice of Random Radio.  
Your job: duck the music, read the title out loud, play a short
FX stinger, then speak a two‑sentence “host” line that describes the
song.  
Return only the commentary string – nothing else.
"""

def _build_prompt(title: str, track: pathlib.Path) -> str:
    """Return the JSON that Ollama receives."""
    return f"""{{"title":"{title}","track":"{track.name}"}}"""

def _load_context() -> str:
    """Optional – try to embed a bit of context from the README."""
    return ""

SYSTEM_PROMPT = f"""
You are the DJ host for Random Radio.  Speak the title of the track,
then a short two‑sentence “host” line.  Keep it natural – a
hand‑crafted voice‑over in a voice‑engine.  You should *only* return
the commentary – no other keys.
"""

# ------------------------------------------------------------------ #
# Ollama
# ------------------------------------------------------------------ #
OLLAMA = Client()  # global – re‑using a single client is fine

def ask_ollama(prompt: str) -> str:
    """
    Ask the local Ollama model and return the raw text response.
    We *block* here because commentary is short (≤ 30 s).
    """
    try:
        r = OLLAMA.generate(
            model=DEFAULT_OLLAMA_MODEL,
            prompt=prompt,
            stream=False,  # we want the finished text in one go
        )
        # `generate` returns a dict with a `response` key
        return r.get("response", "").strip()
    except Exception as exc:  # pragma: no cover
        logging.warning("Ollama failed – falling back to canned commentary: %s", exc)
        return "Sorry, I couldn’t fetch a host line right now."

# ------------------------------------------------------------------ #
# Audio helpers
# ------------------------------------------------------------------ #
def build_albums(root: pathlib.Path) -> Dict[str, List[pathlib.Path]]:
    """Walk the directory tree and return a mapping of album → list of tracks."""
    if not root.is_dir():
        logging.error("Albums root %s does not exist", root)
        return {}

    albums: Dict[str, List[pathlib.Path]] = {}
    for album_dir in root.iterdir():
        if not album_dir.is_dir():
            continue
        tracks = [
            f
            for f in album_dir.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
        ]
        if tracks:
            albums[album_dir.name] = sorted(tracks)

    if not albums:
        logging.warning("No audio files found under %s", root)
    return albums


# ------------------------------------------------------------------ #
# TTS wrapper (non‑blocking)
# ------------------------------------------------------------------ #
class TTS:
    """Thin wrapper around pyttsx3 that guarantees non‑blocking."""

    def __init__(self) -> None:
        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", DEFAULT_TALK_RATE)
        self.engine.setProperty("volume", DEFAULT_TALK_VOL)
        self._lock = threading.Lock()

    def list_voices(self) -> List[Dict[str, str]]:
        """Return a list of available voices."""
        return [
            {"name": v.name, "id": v.id}
            for v in self.engine.getProperty("voices")
        ]

    def set_voice(self, substring: str) -> Optional[str]:
        """Select a voice that contains `substring` (case‑insensitive)."""
        if not substring:
            return None
        for voice in self.engine.getProperty("voices"):
            if substring.lower() in voice.name.lower():
                self.engine.setProperty("voice", voice.id)
                return voice.id
        return None

    def speak(self, text: str) -> None:
        """Speak *in a background thread* so the caller never blocks."""
        def _run() -> None:
            with self._lock:
                self.engine.say(text)
                self.engine.runAndWait()

        threading.Thread(target=_run, daemon=True).start()


# ------------------------------------------------------------------ #
# Core DJ / radio class
# ------------------------------------------------------------------ #
class RandomRadio:
    """
    Public API – this is the class that Streamlit imports.
    All heavy work (VLC, TTS, Ollama) lives in here.
    """

    def __init__(
        self,
        albums: Dict[str, List[pathlib.Path]],
        endless: bool = True,
        export_csv: Optional[pathlib.Path] = None,
        duck_to: int = DEFAULT_DUCK_TO,
        music_vol: int = DEFAULT_MUSIC_VOL,
        fx_dir: Optional[pathlib.Path] = None,
        voice_match: Optional[str] = None,
        db_dsn: Optional[str] = None,
    ) -> None:
        # ---- 1️⃣  data ----------------------------------------------- #
        self.albums = albums
        self.endless = endless
        self.export_csv = export_csv
        self.duck_to = duck_to
        self.music_vol = music_vol
        self.fx_dir = fx_dir if fx_dir and fx_dir.is_dir() else None
        self.db_dsn = db_dsn

        # ---- 2️⃣  player ---------------------------------------------- #
        self._vlc = vlc.Instance(
            "--intf", "dummy", "--no-video", "--quiet"
        )
        self.player = self._vlc.media_player_new()
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached, self._on_track_end
        )

        # ---- 3️⃣  TTS ----------------------------------------------- #
        self.tts = TTS()
        if voice_match:
            self.tts.set_voice(voice_match)

        # ---- 4️⃣  state ---------------------------------------------- #
        self.queue: List[Tuple[str, pathlib.Path]] = []
        self.current_index = 0
        self.is_playing = False
        self.lock = threading.Lock()
        self.history: List[Dict[str, str]] = []

        self._rebuild_queue()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _rebuild_queue(self) -> None:
        """Populate / shuffle the internal queue."""
        self.queue = [
            (album, track)
            for album, tracks in self.albums.items()
            for track in tracks
        ]
        random.shuffle(self.queue)
        logging.info("Loaded %d tracks in %d albums", len(self.queue), len(self.albums))

    def _choose_next_by_mood(self, current: Tuple[str, pathlib.Path]) -> Optional[pathlib.Path]:
        """Ask the model for a track name and return the matching Path."""
        album, cur_track = current
        prompt = f"""{{"album":"{album}","track":"{cur_track.name}"}}"""
        try:
            response = ask_ollama(prompt)
        except Exception:  # pragma: no cover
            return None

        # normalise the answer (strip extension & whitespace)
        ans = response.strip().lower()
        if not ans:
            return None

        # we want just the stem – the model may return “song.mp3”
        stem = pathlib.Path(ans).stem
        _, track_path = next(
            (
                a, p
                for a, p in self.title_map.items()
                if a == album and p.stem.lower() == stem
            ),
            (None, None),
        )
        return track_path

    @property
    def title_map(self) -> Dict[str, Tuple[str, pathlib.Path]]:
        """Return a dict stem→(album,path).  Re‑build on‑demand."""
        d: Dict[str, Tuple[str, pathlib.Path]] = {}
        for album, tracks in self.albums.items():
            for track in tracks:
                d[track.stem.lower()] = (album, track)
        return d

    # ------------------------------------------------------------------ #
    # Event handler (run from VLC thread)
    # ------------------------------------------------------------------ #
    def _on_track_end(self, event: Optional[vlc.libvlc_event_t]) -> None:
        """Triggered by VLC when a track finishes."""
        with self.lock:
            # 1️⃣  increment index
            self.current_index = (self.current_index + 1) % len(self.queue)
            # 2️⃣  apply mood (if any)
            if self.mood_hint:
                mood_path = self._choose_next_by_mood(self.queue[self.current_index])
                if mood_path:
                    # move the mood track to the front
                    self.queue.insert(0, mood_path)
                    self.current_index = 0
            # 3️⃣  start the next song
            self._play_current()

    # ------------------------------------------------------------------ #
    # Playback
    # ------------------------------------------------------------------ #
    def _play_current(self) -> None:
        """Play the track at `self.current_index` and log the commentary."""
        if not self.queue:
            logging.error("Queue is empty – nothing to play.")
            return

        album, track = self.queue[self.current_index]
        logging.info("Now playing %s → %s", album, track.name)

        # a) start the music
        self.player.stop()
        media = self._vlc.media_new(str(track))
        self.player.set_media(media)
        self.player.audio_set_volume(self.music_vol)
        self.player.play()

        # b) run the FX & TTS *in parallel* (so UI never blocks)
        commentary = self._host_commentary(album, track.name)
        # we intentionally do NOT `join()` – the commentary will finish
        # in its own thread, while the music will play *after* it’s done.

        # c) log the result
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "album": album,
            "track": track.name,
            "commentary": commentary,
        }
        self.history.append(entry)

        if self.export_csv:
            try:
                with open(self.export_csv, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([entry[k] for k in ("timestamp", "album", "track", "commentary")])
            except Exception as exc:  # pragma: no cover
                logging.warning("CSV write failed: %s", exc)

        # d) (optional) insert into DB
        if self.db_conn:
            try:
                self._insert_history_db(album, track.name, commentary)
            except Exception:  # pragma: no cover
                logging.warning("DB insert failed – continuing")

    def _host_commentary(self, album: str, track_name: str) -> str:
        """
        Ask Ollama for the host line and return it.
        The function *does not block* – the TTS engine runs in a
        background thread, so the music can start immediately.
        """
        prompt = f"DJ, what are you saying about {track_name}?"
        commentary = ask_ollama(prompt)

        # duck‑ing
        self.player.audio_set_volume(self.duck_to)

        # play FX – no error if file missing
        self._play_fx("airhorn")

        # run TTS in its own thread
        self.tts.speak(commentary)

        # restore music volume
        self.player.audio_set_volume(self.music_vol)

        return commentary

    def _play_fx(self, name: str) -> None:
        """Play a short FX stinger (airhorn, etc.).  Silently ignore if missing."""
        if not self.fx_dir:
            return
        for ext in SUPPORTED_EXT:
            fx_path = self.fx_dir / f"{name}{ext}"
            if fx_path.is_file():
                media = self._vlc.media_new(str(fx_path))
                fx_player = self._vlc.media_player_new()
                fx_player.set_media(media)
                fx_player.play()
                # we don't care about stopping the FX – libvlc will free it
                break

    # ------------------------------------------------------------------ #
    # Public API – thread‑safe
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the player – runs forever until KeyboardInterrupt."""
        if not self.queue:
            logging.error("No tracks to play – aborting.")
            return

        self._play_current()
        try:
            while True:
                time.sleep(1)
                # watchdog – restart if VLC has gone silent
                if not self.is_playing and not self.player.is_playing():
                    logging.warning("Player stalled – restarting.")
                    self._play_current()
        except KeyboardInterrupt:
            logging.info("Interrupted – shutting down.")
            self.stop_all()

    def stop_all(self) -> None:
        self.player.stop()
        if self.db_conn:
            self.db_conn.close()

    def skip(self) -> None:
        with self.lock:
            self.player.stop()
            self._on_track_end(None)

    def previous(self) -> None:
        with self.lock:
            self.current_index = max(0, self.current_index - 1)
            self.player.stop()
            self._play_current()

    def pause(self) -> None:
        with self.lock:
            self.player.pause()
            self.is_playing = False

    def play(self) -> None:
        with self.lock:
            self.player.play()
            self.player.audio_set_volume(self.music_vol)
            self.is_playing = True

    def current_track_info(self) -> dict:
        album, track = self.queue[self.current_index]
        return {"album": album, "track": track.name}

    def list_voices(self) -> List[Dict[str, str]]:
        return self.tts.list_voices()

    def set_voice(self, match: str) -> Optional[str]:
        return self.tts.set_voice(match)

    def perform_command(self, cmd: str) -> dict:
        """Convenient text command interface – useful for the Streamlit UI."""
        cmd = (cmd or "").strip().lower()
        if cmd in ("skip", "next"):
            self.skip()
            return {"action": "skipped"}
        if cmd in ("prev", "previous", "back"):
            self.previous()
            return {"action": "previous"}
        if cmd in ("pause", "stop"):
            self.pause()
            return {"action": "paused"}
        if cmd == "play":
            self.play()
            return {"action": "playing"}
        if cmd.startswith("mood "):
            mood = cmd[5:].strip()
            self.mood_hint = mood
            return {"action": "mood-set", "mood": mood}
        if cmd == "mood":
            self.mood_hint = None
            return {"action": "mood-cleared"}
        if cmd == "now":
            return {"now": self.current_track_info()}
        if cmd.startswith("voice "):
            voice = cmd[6:].strip()
            chosen = self.set_voice(voice)
            return {"action": "voice-chosen", "voice": chosen}
        return {"error": "unknown command"}

# ------------------------------------------------------------------ #
# CLI – optional; keeps the original “stand‑alone” behaviour
# ------------------------------------------------------------------ #
def main() -> None:
    parser = argparse.ArgumentParser(description="Random Radio (Research Radio) with Ollama host.")
    parser.add_argument("--albums-root", type=str, default=str(ROOT_ALBUMS), help="Root folder with albums")
    parser.add_argument("--ollama-model", type=str, default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument("--export-csv", type=str, help="CSV file for history")
    parser.add_argument("--db-dsn", type=str, help="MySQL DSN: mysql://user:pass@host/db")
    parser.add_argument("--no-loop", dest="loop", action="store_false", help="Do not loop library")
    parser.add_argument("--voice", type=str, help="TTS voice substring to select")
    parser.add_argument("--duck-to", type=int, default=DEFAULT_DUCK_TO, help="Volume during talk (0‑100)")
    parser.add_argument("--music-vol", type=int, default=DEFAULT_MUSIC_VOL, help="Music volume (0‑100)")
    parser.add_argument("--fx-dir", type=str, default=str(DEFAULT_FX_DIR), help="Folder with FX stingers (optional)")

    args = parser.parse_args()

    root = pathlib.Path(args.albums_root)
    if not root.is_dir():
        logging.error("Albums root %s does not exist", root)
        sys.exit(1)

    albums = build_albums(root)
    if not albums:
        logging.error("No albums with audio tracks found – aborting.")
        sys.exit(1)

    fx_dir = pathlib.Path(args.fx_dir) if args.fx_dir else None

    radio = RandomRadio(
        albums,
        endless=args.loop,
        export_csv=pathlib.Path(args.export_csv) if args.export_csv else None,
        db_dsn=args.db_dsn,
        duck_to=args.duck_to,
        music_vol=args.music_vol,
        fx_dir=fx_dir,
        voice_match=args.voice,
    )
    radio.start()


if __name__ == "__main__":
    main()
