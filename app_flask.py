#!/usr/bin/env python3
"""
app_flask.py – a tiny web interface to the RandomRadio class.
"""

from pathlib import Path
import threading
import logging

from flask import Flask, render_template, request, redirect, url_for, jsonify

# Import the radio class
from random_radio_ollama import RandomRadio, ask_llm, DEFAULT_OLLAMA_MODEL

# ----------------------------------------------------------------------
# Load the radio instance (you can tweak the args here; later you could load
# from env‑vars, a config file, or the existing ``main()`` logic.)
# ----------------------------------------------------------------------
ROOT_ALBUMS = Path("/Volumes/Elements/Old Laptop/Disc D/albums")
ALBUMS_ROOT = ROOT_ALBUMS if ROOT_ALBUMS.is_dir() else Path("./albums")
RADIO = RandomRadio(
    build_albums(ALBUMS_ROOT),
    endless=True,
    model=DEFAULT_OLLAMA_MODEL,
    export_csv=Path("history.csv"),
)

# Start the radio loop in a background thread so the Flask server stays responsive
def _radio_loop():
    RADIO.start()          # this blocks until you hit Ctrl‑C
t = threading.Thread(target=_radio_loop, daemon=True)
t.start()

# ----------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index():
    info = RADIO.current_track_info()
    history = RADIO.history[-12:]  # last 12 plays
    return render_template(
        "index.html",
        album=info["album"],
        track=info["track"],
        history=history,
    )


@app.route("/skip", methods=["POST"])
def skip():
    RADIO.skip()
    return redirect(url_for("index"))


@app.route("/pause", methods=["POST"])
def pause():
    RADIO.player.pause()
    return redirect(url_for("index"))


@app.route("/play", methods=["POST"])
def play():
    RADIO.player.play()
    return redirect(url_for("index"))


@app.route("/command", methods=["POST"])
def command():
    cmd = request.form.get("cmd", "")
    RADIO.perform_command(cmd)
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Simple API – useful if you want a front‑end that talks to it via JS
# ----------------------------------------------------------------------
@app.route("/api/now")
def api_now():
    return jsonify(RADIO.current_track_info())


@app.route("/api/history")
def api_history():
    return jsonify(RADIO.history)


# ----------------------------------------------------------------------
# Run if this file is executed directly
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    # Make sure static and template folders are found (just in case you run from elsewhere)
    app.run(host="0.0.0.0", port=8080, threaded=True)
