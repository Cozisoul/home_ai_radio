#!/usr/bin/env python3
"""
Random Radio – Portable DJ powered by VLC, Ollama & (optional) Pillow.

Author : 2024‑09‑13 – OpenAI ChatGPT
"""

# ----------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------
import argparse
import csv
import pathlib
import random
import threading
import time
import sys
import os

import vlc
from typing import Dict, List, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None  # Pillow optional – only for debug screenshots

try:
    import ollama
except Exception:
    ollama = None  # Ollama optional – only for commentary generation

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
DEFAULT_MODEL = "gemma3:4b"
DEFAULT_DUCK_TO = 20      # % volume when DJ speaks
DEFAULT_MUSIC_VOL = 80    # % volume when music plays
SUPPORTED_EXT = (".mp3", ".wav", ".ogg", ".flac", ".aac")

# ----------------------------------------------------------------------
# Utility – flatten the album map into a shuffled queue
# ----------------------------------------------------------------------
def build_queue(albums: Dict[str, List[pathlib.Path]]) -> List[tuple]:
    """Return a shuffled list of (album, track_path) tuples."""
    queue = [(album, track) for album, tracks in albums.items() for track in tracks]
    random.shuffle(queue)
    return queue


# ----------------------------------------------------------------------
# TTS helper (debug only)
# ----------------------------------------------------------------------
class TTS:
    def __init__(self):
        self.font = None
        if Image is None:
            return
        try:
            self.font = ImageFont.load_default()
        except Exception:
            pass

    def render(self, text: str, output: pathlib.Path) -> pathlib.Path:
        """Render a tiny PNG that contains *text* – useful only in debug mode."""
        if Image is None:
            return output
        img = Image.new("RGB", (400, 200), "black")
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, font=self.font, fill=(255, 255, 255))
        output.parent.mkdir(parents=True, exist_ok=True)
        img.save(output)
        return output


# ----------------------------------------------------------------------
# Main DJ class
# ----------------------------------------------------------------------
class RandomRadio:
    """
    The DJ engine – plays music via VLC, ducks volume, queries Ollama for
    commentary, plays short FX, and (optionally) writes a CSV history.
    """

    def __init__(
        self,
        albums: Dict[str, List[pathlib.Path]],
        model: str = DEFAULT_MODEL,
        export_csv: Optional[pathlib.Path] = None,
        fx_dir: Optional[pathlib.Path] = None,
        duck_to: int = DEFAULT_DUCK_TO,
        music_vol: int = DEFAULT_MUSIC_VOL,
    ):
        # ------------------------------------------------------------------
        # Album / FX / CSV / config
        # ------------------------------------------------------------------
        self.albums = albums
        self.fx_dir = fx_dir if fx_dir and fx_dir.is_dir() else None
        self.duck_to = duck_to
        self.music_vol = music_vol
        self.export_csv = export_csv
        self.model = model

        # ------------------------------------------------------------------
        # VLC – a *plain* MediaPlayer – no Instance() needed (works everywhere)
        # ------------------------------------------------------------------
        self.player = vlc.MediaPlayer()
        self.player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEndReached, self._on_track_end
        )

        # ------------------------------------------------------------------
        # TTS – Pillow debugging only
        # ------------------------------------------------------------------
        self.tts = TTS()

        # ------------------------------------------------------------------
        # State
        # ------------------------------------------------------------------
        self.queue = build_queue(albums)
        self.idx = 0
        self.lock = threading.Lock()
        self.mood_hint = None
        self.history: List[Dict] = []

    # ------------------------------------------------------------------
    # VLC event callback – advance queue on track finish
    # ------------------------------------------------------------------
    def _on_track_end(self, event):
        with self.lock:
            self.idx = (self.idx + 1) % len(self.queue)
        self._play_current()

    # ------------------------------------------------------------------
    # Public API – kick the DJ loop
    # ------------------------------------------------------------------
    def start(self):
        self._play_current()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n🛑 Stopping…")
            self.player.stop()
            sys.exit(0)

    # ------------------------------------------------------------------
    # Internal helpers – no self.vlc_inst references
    # ------------------------------------------------------------------
    def _play_current(self):
        album, track = self.queue[self.idx]
        # Stop any previous playback
        self.player.stop()

        # Create a Media object for the track
        media = vlc.Media(str(track))
        self.player.set_media(media)

        # Normal music volume
        self.player.audio_set_volume(self.music_vol)
        self.player.play()

        # Generate commentary (ducks, FX, Ollama)
        commentary = self._host_commentary(album, track.name)

        # Persist history / optional CSV
        self.history.append(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "album": album,
                "track": track.name,
                "commentary": commentary,
            }
        )
        if self.export_csv:
            self._write_csv(commentary)

    def _host_commentary(self, album: str, track_name: str) -> str:
        """Duck, play FX, call Ollama, restore volume."""
        # 1️⃣ Duck
        self.player.audio_set_volume(self.duck_to)

        # 2️⃣ FX – optional
        self._play_fx("airhorn")

        # 3️⃣ Commentary from Ollama
        commentary = self._query_ollama(album, track_name)

        # 4️⃣ TTS – Pillow debug only
        self.tts.render(commentary, pathlib.Path(f"./tmp/{album}-{track_name}.png"))

        # 5️⃣ Restore music volume
        self.player.audio_set_volume(self.music_vol)

        return commentary

    def _query_ollama(self, album: str, track_name: str) -> str:
        if ollama is None:
            return f"[Ollama not available] {album} – {track_name}"
        prompt = f"DJ‑style commentary on {album} – {track_name}"
        try:
            res = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            return res.get("message", {}).get("content", "…")
        except Exception as exc:
            return f"[Ollama error] {exc}"

    def _write_csv(self, commentary: str):
        """Append a row to the CSV file (create header if empty)."""
        row = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "album": self.queue[self.idx][0],
            "track": self.queue[self.idx][1].name,
            "commentary": commentary,
        }
        with self.export_csv.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if f.tell() == 0:
                writer.writeheader()
            writer.writerow(row)

    def _play_fx(self, name: str):
        """Play a short FX file (e.g. airhorn.wav)."""
        if not self.fx_dir:
            return
        for ext in SUPPORTED_EXT:
            fx = self.fx_dir / f"{name}{ext}"
            if fx.is_file():
                fx_player = vlc.MediaPlayer(str(fx))
                fx_player.play()
                break

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    def current_track(self) -> tuple:
        return self.queue[self.idx]

    def current_album(self) -> str:
        return self.queue[self.idx][0]

    def current_track_name(self) -> str:
        return self.queue[self.idx][1].name


# ----------------------------------------------------------------------
# Discover all audio files under a root directory
# ----------------------------------------------------------------------
def discover_albums(root: pathlib.Path) -> Dict[str, List[pathlib.Path]]:
    albums: Dict[str, List[pathlib.Path]] = {}
    for path in root.rglob("*"):
        if path.suffix.lower() in SUPPORTED_EXT:
            album = path.parent.name
            albums.setdefault(album, []).append(path)
    return albums


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Random Radio DJ – VLC + Ollama + optional Pillow debug"
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
        help="Root directory containing your music (default: CWD)",
    )
    parser.add_argument(
        "--csv",
        type=pathlib.Path,
        help="Optional CSV file to append playback history",
    )
    parser.add_argument(
        "--fx",
        type=pathlib.Path,
        help="Directory that contains short FX files (e.g. airhorn.wav)",
    )
    parser.add_argument(
        "--duck",
        type=int,
        default=DEFAULT_DUCK_TO,
        help="Duck volume (0‑100) when the DJ speaks",
    )
    parser.add_argument(
        "--vol",
        type=int,
        default=DEFAULT_MUSIC_VOL,
        help="Music playback volume (0‑100)",
    )
    args = parser.parse_args()

    print(f"🔍 Scanning {args.root} …")
    albums = discover_albums(args.root)
    if not albums:
        print("❌ No audio files found – aborting.")
        sys.exit(1)

    print(f"🎵 Found {len(albums)} albums, {sum(len(v) for v in albums.values())} tracks.")
    radio = RandomRadio(
        albums=albums,
        export_csv=args.csv,
        fx_dir=args.fx,
        duck_to=args.duck,
        music_vol=args.vol,
    )
    radio.start()


if __name__ == "__main__":
    main()
