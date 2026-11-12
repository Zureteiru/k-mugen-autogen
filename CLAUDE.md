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
Download best video (.mp4) once (also the alignment input)
       │
       ▼ [syncedlyrics + fast_lyrics.py]
Fetch Synchronized LRC (or unsynced plain text)
       │
       ▼ [audio-separator / UVR-MDX-NET (optional / as needed)]
Isolate Vocal Stem
       │
       ▼ [aligner.py + stable-ts (Stable-Whisper)]
Acoustic Forced Alignment (one global pass + per-line gate, LRC-anchored window fallback)
       │
       ▼ [japanese_utils.py + fugashi/unidic-lite]
Phonological Japanese Romanization & Mora Segmentation
       │
       ▼ [ass_compiler.py]
Karaoke Mugen (kara.moe) house style, drift-free centisecond {\k} tagging -> .ass File
       │
       ▼ [main.py]
mpv playback (if mpv is on PATH)
```

---

## 2. Architecture & File Reference

| File | Purpose |
| :--- | :--- |
| [`main.py`](file:///main.py) | CLI entrypoint (positional `source`, optional `--artist`/`--title`), single yt-dlp download, pipeline orchestration, and a plain `mpv` launcher. |
| [`aligner.py`](file:///aligner.py) | Audio forced alignment using `stable-ts` (Whisper). Implements one global whole-track alignment, a per-line plausibility gate, window re-alignment against the LRC guide with a median offset, and vocal stem isolation via MDX-Net (stems identified by the `(Vocals)` / `(Instrumental)` filename marker). |
| [`japanese_utils.py`](file:///japanese_utils.py) | Japanese linguistic parser built on fugashi + unidic-lite. Sokuon (`っ`/`ッ`) consonant gemination, small kana (`ゃ`/`ゅ`/`ょ`/`ぁ`...) contraction, particle `は` -> `wa` / `へ` -> `e`, `ー` vowel repetition, and part-of-speech based word-space suppression. |
| [`ass_compiler.py`](file:///ass_compiler.py) | Compiles `LyricLine` data into Advanced SubStation Alpha (`.ass`) format. Emits the official Karaoke Mugen template output (styles, templater Comment, `karaoke` Comment + `fx` Dialogue per line) with continuous absolute centisecond timing to prevent drift. |
| `ui_server.py` + `ui/` | Local test bench (`.venv/bin/python ui_server.py` -> http://127.0.0.1:8765): libass preview via vendored JASSUB 1.8.8, pipeline runner, romaji/LRC lab, pytest runner. |
| [`fast_lyrics.py`](file:///fast_lyrics.py) | Lyrics fetcher using `syncedlyrics` (returns plain text when no timestamps exist). Parses Standard `[mm:ss.xx]` and Enhanced `<mm:ss.xx>` LRC lines, per line, into line objects. |
| [`models.py`](file:///models.py) | Dataclasses: `MoraTiming` and `LyricLine`. |
| [`tests/test_core.py`](file:///tests/test_core.py) | pytest regression tests (offline; no Whisper, torch, yt-dlp or network). |
| `output/` | Generated `.ass` files ready for Karaoke Mugen or `mpv` (git-ignored). |

---

## 3. What Was Completed & Works Well

1. **Strict Japanese Phonological Rules ([`japanese_utils.py`](file:///japanese_utils.py)):**
   - **Sokuon Gemination:** `っ` / `ッ` is strictly geminated to the succeeding consonant (e.g. `kitto`, `nemutta`, `bakku`, `itchatte`). Never rendered as literal `tsu`.
   - **Morphological analysis:** readings and parts of speech come from fugashi + unidic-lite.
   - **Particle conversion:** particle `は` -> `wa`, particle `へ` -> `e`; `ー` repeats the previous vowel.
   - **Grammatical suffix cohesion:** auxiliaries, conjunctive particles and suffixes (`た`, `て`, `ない`, `たい`, `ます`) stay attached to the preceding stem without unintended spaces.
2. **Karaoke Mugen (kara.moe) ASS Style & Drift-Free Centisecond Tracking ([`ass_compiler.py`](file:///ass_compiler.py)):**
   - Mirrors the official KM template (https://docs.karaokes.moe/aegisub/sampleKaraokeMugen.ass) as Aegisub leaves it after "Apply karaoke template": `PlayResX/Y: 0`, the `Sample KM [Up]` style (bold Arial 24, top of screen, white filling orange `&H00008AFF`, 1.5 outline), the templater `Comment`, and per line a `karaoke` Comment plus an `fx` Dialogue.
   - Each line appears 0.9 s early (lead filled by an empty `\k90`, or `\k<start>` for lines before 0.9 s), `\fad(300,200)`, and stays 0.2 s after the last syllable. Lines overlap on purpose, so libass stacks current + next line (the kara.moe two-line look).
   - Syllables use `\k`; `\kf` only for syllables over 100 cs (KM convention). Romaji only, no Kanji line.
   - Continuous `current_sec` tracking from `event_start_sec`: pauses between words or vocal rests are dynamically encoded as silent `{\k{gap_cs}}` tags, ensuring that later syllables highlight at their exact acoustic time rather than drifting.
3. **Songs used during development** (their old `.ass` outputs predate the remediation, are no longer tracked and are only in git history; regenerate them rather than trusting them):
   - *Sakanaction - Shin Takarajima*, *Sakanaction - Ame(A)*, *RADWIMPS - Hyperventilation*, *KOTOKO - I pray to stop my cry*, *rerulili - Brain Fluid Explosion Girl*

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

# Run the regression tests (offline):
.venv\Scripts\python.exe -m pytest -q tests/
```
