# 🎧 Random Radio – Research Radio

A tiny local‑host radio station that:

* Plays every track found under an *albums* directory
  (one track per album sub‑folder).
* Generates a 2‑sentence “DJ host” line for every track using
  Ollama **locally**.
* Ducks the music while the host speaks and can play short FX
  (“airhorn”, “rewind”, …).
* Lets you choose any `pyttsx3` voice by substring.
* Supports a *mood* cue to influence the next track selection.
* Logs every play to a CSV file and displays the history in a
  Streamlit UI.
* Comes with a `streamlit` front‑end (`app_streamlit.py`) that
  imports the same core library (`random_radio_ollama.py`).

## 🛠️ Prerequisites

| Component | Minimum version |
|-----------|-----------------|
| Python | 3.9+ |
| libvlc | See “Installation” section below |
| Ollama server | Local server with the model `research_radio_host` (or whatever you choose) |

### libvlc

* macOS: `brew install vlc`
* Ubuntu: `sudo apt install vlc`

> libvlc must be in your `PATH`.  If you cannot get VLC working
>  you will see the error *“Failed to load the VLC plugin”* in the
>  logs.

## 📦 Installation

```bash
# 1. Clone the repo
git clone https://github.com/<your‑user>/random-radio.git
cd random-radio

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .\.venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install -r requirements.txt
