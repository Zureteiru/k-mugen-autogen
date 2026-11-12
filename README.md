# k-mugen-autogen 🎤

Automated, high-fidelity **Karaoke Mugen** `.ass` subtitle generator with acoustic Japanese forced alignment and phonological romanization.

Given a YouTube URL or media file, `k-mugen-autogen`:
1. Downloads the highest quality audio/video streams via `yt-dlp`.
2. Searches and fetches synchronized LRC lyrics via `syncedlyrics`.
3. Optionally isolates vocal stems with MDX-Net via `audio-separator`.
4. Performs forced alignment using `stable-ts` (Stable-Whisper) on GPU or CPU.
5. Converts Japanese kanji/kana to romanized morae with strict phonological rules (geminated sokuon, particles, compound kana).
6. Compiles drift-free centisecond Karaoke Mugen `.ass` files with `\k` and `\kf` highlight tags.
7. Launches interactive `mpv` player with synchronized video and audio.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10+
- `mpv` installed (optional, for real-time playback testing)
- NVIDIA GPU with CUDA (optional, but recommended for Whisper and stem separation)

### Installation
```bash
git clone https://github.com/Zureteiru/k-mugen-autogen.git
cd k-mugen-autogen
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Usage
```bash
# Run on a YouTube song and launch mpv on completion
python main.py "https://youtu.be/Ey_NHZNYTeE"

# Run in background without launching mpv
python main.py "https://youtu.be/nueJvP-eMU0" --no-play

# Process with explicit title and artist overrides
python main.py "https://youtu.be/OEPmMz2Y0c8" --title "Hyperventilation" --artist "RADWIMPS"
```

Output `.ass` files are saved to the `output/` directory.

---

## 🛠️ Features

- **Strict Phonological Romanization:**
  - Geminated consonants for sokuon `っ` / `ッ` (e.g. `kitto`, `nemutta`, `itchatte` — never `tsu`).
  - Contextual `は` -> `wa` particle conversion.
  - Compound kana (`きゃ` -> `kya`, `ちゃ` -> `cha`, `ティ` -> `ti`).
  - Pre-pass repairs for split kanji stems before small kana (`来ちゃった` -> `kichatta`).
  - Bound verb and adjective suffixes (`た`, `て`, `ない`, `たい`, `ます`) stay attached without unwanted word spaces.
- **Drift-Free Centisecond Accumulator:**
  - Automatically calculates silent `\k{gap_cs}` intervals for pauses and rests so syllables don't drift across long lines.
- **Global & Slice Alignment Hierarchy:**
  - Resolves multi-second intro sequence offsets between web album LRCs and YouTube music video intros using global forced alignment with offset probing.
- **Windows Interactive Desktop Bridge:**
  - Routes `mpv` playback to active user sessions via Task Scheduler when run from sandboxed CLI agents.

---

## 📖 Handover & Next Steps

See [`CLAUDE.md`](file:///CLAUDE.md) for detailed architectural documentation, known edge cases (video intro offsets, intra-word mora hold durations), and roadmap.
