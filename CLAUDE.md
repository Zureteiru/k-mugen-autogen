# CLAUDE.md - Handover & Technical Context for k-mugen-autogen

This document summarizes the current state, technical decisions, completed features, known failures, and next steps for **k-mugen-autogen** (Automated Karaoke Mugen `.ass` Subtitle Generator).

---

## 1. Project Mission & Core Workflow

**k-mugen-autogen** is a Python CLI pipeline designed to generate production-ready, acoustically synchronized Karaoke Mugen Romaji subtitle files (`.ass`) from YouTube music video URLs or local media files.

### End-to-End Pipeline
```
YouTube URL / Local Audio & Video
       │
       ▼ [yt-dlp]
Download Best Video (.mp4) + Audio (.webm / .mp3)
       │
       ▼ [syncedlyrics + fast_lyrics.py]
Fetch Synchronized LRC (with localized / romanized artist aliases)
       │
       ▼ [audio-separator / UVR-MDX-NET (optional / as needed)]
Isolate Vocal Stem
       │
       ▼ [aligner.py + stable-ts (Stable-Whisper)]
Acoustic Forced Alignment (Global DP or LRC-anchored Window Alignment)
       │
       ▼ [japanese_utils.py + pykakasi]
Phonological Japanese Romanization & Mora Segmentation
       │
       ▼ [ass_compiler.py]
Continuous Drift-Free Centisecond Tagging ({\k} / {\kf}) -> .ass File
       │
       ▼ [main.py]
Interactive Desktop mpv Playback Bridge (Windows Task Scheduler / Session 1)
```

---

## 2. Architecture & File Reference

| File | Purpose |
| :--- | :--- |
| [`main.py`](file:///main.py) | CLI entrypoint, argument parsing, pipeline orchestration, and Windows desktop `mpv` launcher with interactive session bridge. |
| [`aligner.py`](file:///aligner.py) | Audio forced alignment using `stable-ts` (Whisper). Implements global whole-track alignment with slice-window fallback and offset probing. Vocal stem isolation via MDX-Net. |
| [`japanese_utils.py`](file:///japanese_utils.py) | Japanese linguistic parser. Sokuon (`っ`/`ッ`) consonant gemination, small kana (`ゃ`/`ゅ`/`ょ`/`ぁ`...) contraction, particle `は` -> `wa` conversion, pykakasi token split repair, bound morpheme space suppression. |
| [`ass_compiler.py`](file:///ass_compiler.py) | Compiles `LyricLine` data into Advanced SubStation Alpha (`.ass`) format. Computes continuous absolute centisecond timing (`\k` / `\kf`) to prevent timing drift. |
| [`fast_lyrics.py`](file:///fast_lyrics.py) | Lyrics fetcher using `syncedlyrics` with fallback alias search. Parses Standard `[mm:ss.xx]` and Enhanced `<mm:ss.xx>` LRC files into line objects. |
| [`models.py`](file:///models.py) | Dataclasses: `MoraTiming`, `LyricLine`, and `SongBundle`. |
| [`output/`](file:///output/) | Generated `.ass` files ready for Karaoke Mugen or `mpv`. |

---

## 3. What Was Completed & Works Well

1. **Strict Japanese Phonological Rules ([`japanese_utils.py`](file:///japanese_utils.py)):**
   - **Sokuon Gemination:** `っ` / `ッ` is strictly geminated to the succeeding consonant (e.g. `kitto`, `nemutta`, `bakku`, `itchatte`). Never rendered as literal `tsu`.
   - **Pre-pass pykakasi repair:** Fixes splits where pykakasi separates kanji stems before small kana (e.g. `来ちゃった` -> `kichatta` instead of orphaned `ゃ`).
   - **Particle conversion:** Topic particle `は` -> `wa`.
   - **Grammatical suffix cohesion:** Inflectional endings (`た`, `て`, `ない`, `たい`, `ます`) stay attached to the preceding verb/adjective stem without unintended spaces.
2. **Karaoke Mugen ASS Styling & Drift-Free Centisecond Tracking ([`ass_compiler.py`](file:///ass_compiler.py)):**
   - Clean single-layer Romaji subtitle output styled for 1080p karaoke (no distracting duplicate Kanji ruby lines above).
   - Continuous `current_sec` tracking from `event_start_sec`: pauses between words or vocal rests are dynamically encoded as silent `{\k{gap_cs}}` tags, ensuring that later syllables highlight at their exact acoustic time rather than drifting.
3. **Interactive Windows Desktop Playback ([`main.py`](file:///main.py)):**
   - When running inside background agent or sandboxed terminals on Windows, GUI apps normally cannot display to the user's screen.
   - Built an automated bridge via Windows Task Scheduler (`schtasks /create /it /f`) that runs `mpv.exe` directly on the active user session (`Console Session 1`) with `--ontop` and `--autofit=1280x720`.
4. **Tested Songs & Verified Output:**
   - *Sakanaction - Shin Takarajima* (`output/Sakanaction - Shin Takarajima.ass`)
   - *Sakanaction - Ame(A)* (`output/Sakanaction - Ame(A).ass`)
   - *RADWIMPS - Hyperventilation* (`output/RADWIMPS - Hyperventilation.ass`)
   - *KOTOKO - I pray to stop my cry* (`output/KOTOKO - I pray to stop my cry.ass`)
   - *rerulili - Brain Fluid Explosion Girl* (`output/rerulili - Brain Fluid Explosion Girl.ass`)

---

## 4. What Failed / Known Pain Points for Claude to Solve

### 1. Music Video Intro / Outro Timing Desync (Critical)
- **Problem:** Online LRC databases (NetEase, Musixmatch, Lrclib) host lyrics synchronized to **official CD/album audio releases**. In contrast, YouTube music videos frequently contain **intro cinematic sequences, title logos, or sound effects** before the music starts.
- **Example:** In *rerulili - Brain Fluid Explosion Girl* (`Ey_NHZNYTeE`), the YouTube video has an 11.61-second title screen intro (vocals begin at `00:19.02`), whereas the web LRC timestamps the first line at `00:07.41`.
- **Failure Mode:** When slice-based alignment was used, it cropped the audio around `00:07.41`, which was silence in the video. Whisper found no words, leading to collapsed dummy timings or missing lines.
- **Current Fix & Limitation:** In `aligner.py`, global DP forced alignment across the entire audio file is attempted first. If coverage is $\ge 85\%$, it ignores the LRC timestamps entirely and uses the audio waveform directly. However, on noisy audio, long tracks, or extreme vocaloid tuning, global alignment can drop lines or hallucinate repetitions.
- **Recommended Next Step for Claude:** Implement a dynamic cross-correlation or DTW (Dynamic Time Warping) acoustic intro-offset detector that computes the global audio time shift between the album cut / LRC and the YouTube video before slicing.

### 2. Linear Mora Timing Approximation (Within-Word Hold Durations)
- **Problem:** Whisper `base` outputs timestamps at the **word level** (e.g. start and end for `za shou`). Within each word, morae are currently divided into equal slices (`m_dur = total_word_dur / mora_count`).
- **Failure Mode:** In Japanese singing, singers often hold the final vowel of a word (e.g. `za-sho~~~~u`), while the initial consonant mora is very brief. Linear division highlights all syllables at a constant rate instead of matching the singer's vocal hold.
- **Recommended Next Step for Claude:** Use energy/envelope tracking or phoneme-level CTC alignment (e.g., torchaudio CTC forced aligner or Japanese acoustic model like Julius/VOSK) to pinpoint intra-word mora boundaries.

### 3. High-BPM Vocaloid & Dense Rap Articulation
- **Problem:** At 250+ BPM (like *Brain Fluid Explosion Girl*), standard Whisper `base` occasionally merges consecutive fast kana or misinterprets rapid-fire vocaloid phonemes.
- **Workaround in place:** We used Stable-Whisper with original split preservation, but a larger model (`small` or `medium`) or explicit vocal separation prior to alignment yields cleaner boundaries.

### 4. SyncedLyrics Search Fragility
- **Problem:** `syncedlyrics.search(query)` fails if the title contains Romanized vs Japanese kana differences (e.g., "rerulili" vs "れるりり", "Hyperventilation" vs "ハイパーベンチレイション").
- **Current Fix:** We added `_KNOWN_ALIASES` in `fast_lyrics.py`, but a broader fuzzy search or automated title translation fallback would make it zero-touch.

---

## 5. Development & Execution Quickstart

### Virtual Environment
- Environment path: `.venv\Scripts\python.exe`
- Python version: 3.11+
- CUDA PyTorch 2.6 is configured for RTX 3070 GPU acceleration.

### Commands
```powershell
# Run full pipeline for a YouTube song (interactive mpv playback at finish):
.venv\Scripts\python.exe main.py "https://youtu.be/Ey_NHZNYTeE"

# Run in background without opening player window:
.venv\Scripts\python.exe main.py "https://youtu.be/nueJvP-eMU0" --no-play

# Test playback of an existing ASS file on Windows desktop:
.venv\Scripts\python.exe -c "import os; from main import _launch_mpv, _find_mpv_binary; mpv_bin = _find_mpv_binary(); ass = os.path.abspath('output/rerulili - Brain Fluid Explosion Girl.ass').replace('\\', '/'); vid = os.path.abspath('downloads/Ey_NHZNYTeE.mp4').replace('\\', '/'); aud = os.path.abspath('downloads/Ey_NHZNYTeE.webm').replace('\\', '/'); _launch_mpv([mpv_bin, '--ontop', f'--sub-file={ass}', f'--audio-file={aud}', vid])"
```
