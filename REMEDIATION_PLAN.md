# k-mugen-autogen: Remediation Plan

Audit of `master` (2 commits). Put this file in the repo root and run it from Claude Code one step at a time.

## How to run this in Claude Code

Start a session in the repo root and paste:

```
Read REMEDIATION_PLAN.md. Follow the "Ground rules" section exactly.
Execute Step 1 only, run its verification, show me the diff summary, then stop.
```

After reviewing, continue with `Execute Step 2 only ...` and so on. Steps are ordered so each one leaves the tool runnable. Step 9 is the only one that adds a dependency and can be skipped or deferred.

Suggested setup before starting:

```
git checkout -b remediation
```

## Ground rules (for the coding model)

1. Do one step per turn. Do not start the next step until told to.
2. Do not add new classes, config files, wrappers or abstractions beyond what a step names.
3. Do not restyle, rename or reformat code a step does not mention.
4. After every step run `python -m py_compile main.py aligner.py ass_compiler.py fast_lyrics.py japanese_utils.py models.py` and fix any failure before reporting.
5. Commit after each step with message `remediation: step N - <title>`.
6. The audit was done by reading code, without stable-ts, pykakasi, syncedlyrics or audio-separator installed. Before changing code that depends on one of these libraries, confirm the behaviour against the installed version (for example `python -c "import inspect, syncedlyrics; print(inspect.signature(syncedlyrics.search))"`). If the installed library contradicts an assumption in this plan, stop and report instead of improvising.
7. If a step's verification fails and the fix is not obvious, stop and report. Do not loosen a check to make it pass.

## Progress

- [ ] Step 1: Delete dead code
- [ ] Step 2: Fix the CLI contract
- [ ] Step 3: Single download
- [ ] Step 4: Replace the mpv launcher
- [ ] Step 5: Lyrics fetch returns text even without timestamps
- [ ] Step 6: One global alignment pass with a per-line gate
- [ ] Step 7: Fix character-to-token mapping, remove the gap rewrite
- [ ] Step 8: Stem identification
- [ ] Step 9: Romanization via a morphological analyzer (adds a dependency)
- [ ] Step 10: Regression tests
- [ ] Step 11: Docs, requirements, untrack artifacts

---

## Part A: Findings (why each step exists)

| # | Location | What is wrong | Consequence |
|---|----------|---------------|-------------|
| F1 | `aligner.py` `force_align_japanese`, global pass (approx. lines 163-184, 285-288) | Acceptance gate only checks that 85% of lines have at least one word, which forced alignment nearly always satisfies. When the gate rejects and there is no LRC guide, the `if not segments:` block reruns the identical `model.align` call and accepts it. | Garbage timings pass (committed `output/test_sakuretsu.ass` has `{\kf223}ta{\kf222}be{\kf223}ta`, about 2.2 s per mora). The LRC-anchored path rarely runs. Runtime doubles in the reject case. |
| F2 | `aligner.py` offset probe (approx. lines 194-208) | One unvalidated alignment of line 1 against the first 60 s decides a global offset. It shifts each guide line's `start_sec`/`end_sec` in place but not its `morae`. | Any line that falls back to its guide, and the whole song if `main.py` hits its `except` fallback, has a moved event window with unmoved morae. The compiler clamps those to 5 cs flashes. |
| F3 | `aligner.py` Japanese branch (approx. lines 369-424) | Whisper characters are mapped to pykakasi tokens by raw positional index, assuming equal string lengths. Overflow is clamped to the last character. | Any mismatch (internal spaces, dropped words, punctuation) gives every remaining token the same timestamp. Consistent with the `{\kf5}` runs at line ends in three of the six committed outputs. |
| F4 | `aligner.py` gap loop (approx. lines 332-338) | A word after a real pause of more than 2 s is pulled back to the previous word's end with a fabricated duration of 0.25 s per character. The next gap is measured against the fabricated end, so it cascades. | Real timing for the rest of the line is replaced with invented numbers. |
| F5 | `japanese_utils.py` `convert_tokens_to_morae` | pykakasi is a transliterator, not a morphological analyzer. The `は`→`wa` rule and `_ATTACHED_SUFFIXES` only fire when pykakasi happens to emit that exact token. The function mutates the caller's token list. `ー` is emitted as a literal `-` syllable. | Committed output shows `tabeta i`, `awa sete`, `aisa re tamau`, `ge-pasu`. `は` inside a hiragana run stays `ha`; `はは` style tokens become `hawa`. |
| F6 | `main.py` `main()` argparse | `--source`, `--artist`, `--title` are all required flags. README.md and CLAUDE.md pass the URL positionally with artist/title absent. | The documented quickstart exits with an argparse error. |
| F7 | `main.py` `_launch_mpv`, `_is_sandboxed_desktop` | A workaround for the authoring agent's own sandbox shipped as a feature. Writes a `.ps1` where `$` in a title is expanded by PowerShell; file is BOM-less so Windows PowerShell 5.1 misreads Japanese paths. Polls `tasklist` for any `mpv.exe` with no timeout. Task is scheduled for 23:59. | Hangs if another mpv is open. Subtitle file silently not loaded for Japanese names. A killed run leaves a scheduled task that launches mpv at 23:59. |
| F8 | `fast_lyrics.py` `fetch_and_parse_lyrics`, `_parse_lrc` | Plain unsynced lyrics from `syncedlyrics.search` parse to zero lines and are reported as not found. One `<mm:ss>` tag anywhere switches the whole file to enhanced mode and drops lines without word tags. `min(available_time - 0.2, ...)` goes negative for lines under 0.2 s apart. | Usable lyrics discarded; lines silently lost; negative durations. |
| F9 | `main.py` `download_audio_yt_dlp`, `download_video_yt_dlp`, `main()` | Same URL extracted and downloaded twice into the same `%(id)s.%(ext)s` template; mpv is then given the video plus its own audio again. Output path `f"{artist} - {title}.ass"` is unsanitized. | Wasted download; `AC/DC`, `?` or `:` in a name crashes or writes outside `output/` after the GPU work is done. |
| F10 | `aligner.py` `isolate_vocals` | Stems identified by `"vocal"`/`"inst"` substrings in the full filename. Failed model load silently substitutes the default model. | A source file whose name contains either word gets swapped or duplicated stems. Model changes without the user knowing. |

## Part B: Cuts (delete, do not fix)

- `main.py`: `_is_sandboxed_desktop`, the schtasks branch of `_launch_mpv`, `_refresh_windows_path`, `_find_yt_dlp` (never called), hardcoded Chocolatey/WinGet paths in `_find_mpv_binary`, `_ensure_venv`, the second `import shutil`, `SongBundle` usage, `download_audio_yt_dlp`, the sibling `.webm` heuristic.
- `aligner.py`: `_preprocess_lyric_text`, `_LYRIC_PRONUNCIATION_OVERRIDES` (never called), `_get_line_morae_with_context`, unused `_SMALL_KANA`, inline `import re`, the `type("Segment", (), ...)()` fake class, the duplicate global re-alignment block.
- `ass_compiler.py`: `_apply_word_spaces`, unused `_SMALL_KANA`, the unused `Kanji` style line.
- `fast_lyrics.py`: `_KNOWN_ALIASES`, `_tokenize_morae`, unused `_SMALL_KANA`, the `__main__` demo block.
- `models.py`: `MoraTiming.pre_gap_cs`, `MoraTiming.duration_cs`, `LyricLine.translation`, `SongBundle`.
- `find_lyrics.py`, `test_window_align.py`: scratch scripts. The second is named like a test, loads a CUDA model and hits the network at import.
- `requirements.txt`: `pydantic`, `pyyaml` (never imported).
- Tracked artifacts: `output/*.ass`, `downloads/*.lrc`.

---

## Part C: Execution steps

### Step 1: Delete dead code

- **Target:** Everything in Part B except `download_audio_yt_dlp`, the sibling `.webm` heuristic, `_launch_mpv`, `_find_mpv_binary`, `SongBundle` and `_KNOWN_ALIASES` (handled in Steps 3, 4, 5).
- **Action:** Delete only. Replace `_get_line_morae_with_context` and `_tokenize_morae` call sites with direct `get_morae_for_text` calls using its native keys (`mora`, `rom`, `is_token_end`). In `_build_romaji_payload`, use `[m.romaji for m in line.morae]` unconditionally.
- **Constraint:** Do not change any timing arithmetic. Do not change the `Romaji` style line in the ASS header.
- **Verify:** `grep -n "_apply_word_spaces\|_tokenize_morae\|_get_line_morae_with_context\|_preprocess_lyric_text\|_find_yt_dlp\|_refresh_windows_path\|_ensure_venv\|pre_gap_cs" *.py` returns nothing. `git status` shows `find_lyrics.py` and `test_window_align.py` deleted.

### Step 2: Fix the CLI contract

- **Target:** `main.py: main()`; new helper `_safe_filename(s: str) -> str`.
- **Action:**
  - `source` becomes a positional argument.
  - `--artist` and `--title` become optional. For URLs, fill from yt-dlp `info` (`artist` and `track`, else `uploader` and `title`). For a local file with either missing, exit with a clear message.
  - Build the output name with `_safe_filename`, which replaces any of `<>:"/\|?*` and control characters with `_` and strips trailing dots and spaces.
- **Constraint:** Keep `--lyrics-file`, `--remove-vocals`, `--no-play` names and behaviour. This step may temporarily call the existing download functions to obtain `info`; Step 3 cleans that up.
- **Verify:** `python main.py --help` shows `source` as positional. `python -c "from main import _safe_filename as f; print(f('AC/DC: Who?'))"` prints a name with no `/`, `:` or `?`.

### Step 3: Single download

- **Target:** `main.py: download_video_yt_dlp(source: str, output_dir: str = './downloads') -> tuple[str, dict]`; delete `download_audio_yt_dlp`; delete `SongBundle` from `models.py` and its use.
- **Action:** Download once and return `(path, info)`; for a local file return `(abspath, {})`. Use that single path as the alignment input and the mpv input. Delete the sibling `.webm` lookup. Pass `--audio-file=` to mpv only when `--remove-vocals` produced an instrumental stem.
- **Constraint:** Do not change the yt-dlp `format` string, `outtmpl` or `noplaylist`.
- **Verify:** `grep -n "download_audio_yt_dlp\|SongBundle\|\.webm" main.py models.py` returns nothing.

### Step 4: Replace the mpv launcher

- **Target:** `main.py: _launch_mpv(mpv_cmd: list[str]) -> None`, `_find_mpv_binary() -> str | None`.
- **Action:** `_find_mpv_binary` returns `shutil.which("mpv")`. `_launch_mpv` is a single `subprocess.run(mpv_cmd, check=True)`. In `main()`, if the binary is `None`, log the `.ass` path and return normally.
- **Constraint:** No `schtasks`, PowerShell, `tasklist`, `winreg` or `ctypes` code may remain. Keep the mpv flag list unchanged. Remove `run_mpv.ps1` from `.gitignore`.
- **Verify:** `grep -n "schtasks\|powershell\|tasklist\|winreg\|ctypes\|run_mpv" main.py .gitignore` returns nothing.

### Step 5: Lyrics fetch returns text even without timestamps

- **Target:** `fast_lyrics.py: fetch_and_parse_lyrics(artist: str, title: str) -> tuple[str, list[LyricLine] | None] | None`; `_parse_lrc`; the call site in `main.py`.
- **Action:**
  - First confirm the installed `syncedlyrics.search` signature and whether it can return untimed text (ground rule 6).
  - If the returned text has no `[mm:ss]` tags, return `(plain_text, None)` instead of `None`.
  - Otherwise return `("\n".join(original_text...), parsed_lines)`.
  - Decide enhanced vs standard per line: a line with `<mm:ss>` tags uses the word-timed path, any other timestamped line uses the standard path. Merge and sort by start time.
  - Clamp: `duration = max(0.3, min(available_time - 0.2, max(2.0, natural_duration)))`.
  - Delete `_KNOWN_ALIASES` and its retry branch.
- **Constraint:** Do not touch `_is_credit_or_meta` or `_parse_timestamp`. Keep `parse_lrc_text` signature.
- **Verify:**
  ```
  python - <<'EOF'
  from fast_lyrics import parse_lrc_text
  t = "[00:01.00]<00:01.00>あ<00:01.50>い\n[00:03.00]うえ\n[00:03.10]おか"
  ls = parse_lrc_text(t)
  assert len(ls) == 3, len(ls)
  assert all(l.end_sec > l.start_sec for l in ls)
  assert all(m.end_sec > m.start_sec for l in ls for m in l.morae)
  print("ok")
  EOF
  ```

### Step 6: One global alignment pass with a per-line gate

- **Target:** `aligner.py`. Split `force_align_japanese` into:
  - `_align_global(model, audio, lines: list[str], lang: str) -> list[list | None]` (one word list per input line, `None` when missing)
  - `_line_is_plausible(words: list, n_morae: int, prev_end: float, guide: LyricLine | None, offset: float) -> bool`
  - `_align_window(model, audio, text: str, t0: float, t1: float, lang: str) -> list | None`
  - `_shift_line(line: LyricLine, offset: float) -> LyricLine`
  - `force_align_japanese(vocal_path, raw_lyrics_text, lrc_guide_lines=None) -> list[LyricLine]` stays as the orchestrator with the same signature.
- **Action:** Load audio once with `whisper.load_audio`. Run global alignment exactly once. Then:
  ```
  offset = median(global_start[i] - guide[i].start_sec) over lines that have words   # 0.0 if no guide
  for each line i:
      ok = 0.04 <= (end - start) / n_morae <= 1.5
           and start >= prev_end - 0.1
           and (guide is None or abs(start - (guide.start_sec + offset)) < 3.0)
      if not ok and guide:  words = _align_window(guide window shifted by offset); re-check ok
      if still not ok:      use _shift_line(guide, offset) if guide else evenly spaced morae after prev_end
  ```
  `_shift_line` returns a copy via `dataclasses.replace`, shifting `start_sec`, `end_sec` and every mora.
- **Constraint:** Delete the single-line 60 s probe and the second global `model.align` call. Never mutate `lrc_guide_lines` or its elements. Do not change the public signature or return type. Leave the per-line mora assembly (Japanese and English branches) untouched in this step; Step 7 handles it.
- **Verify:** `grep -c "model.align(" aligner.py` prints `2` (one global, one window). `grep -n "g.start_sec = \|g.end_sec = " aligner.py` returns nothing. Then run one real song end to end with `--no-play` and confirm no line in the output has a `\kf` value above 150.

### Step 7: Fix character-to-token mapping, remove the gap rewrite

- **Target:** `aligner.py`, the Japanese branch of line assembly and the `gap > 2.0` loop. Extract the mapping into `_map_tokens_to_times(whisper_chars: list[dict], token_lens: list[int]) -> list[tuple[float, float]]` so Step 10 can test it.
- **Action:**
  - Delete the gap loop entirely.
  - Remove all whitespace from each Whisper word and from each token's `orig` before measuring lengths.
  - If `len(whisper_chars) == sum(token_lens)`, map positionally.
  - Otherwise map each token's range proportionally: `lo = int(pos * W / T)`, `hi = max(lo, int((pos + n) * W / T) - 1)` where `W = len(whisper_chars)`, `T = sum(token_lens)`.
  - After building a line, if mora start times are not non-decreasing, log a warning with the line text.
- **Constraint:** No `min(len(whisper_chars) - 1, ...)` clamp may remain. Do not change the English branch.
- **Verify:**
  ```
  python - <<'EOF'
  from aligner import _map_tokens_to_times as f
  wc = [{"start": i, "end": i + 1} for i in range(6)]
  r = f(wc, [2, 2, 2, 2, 2])            # 10 token chars onto 6 whisper chars
  assert all(b[0] >= a[0] for a, b in zip(r, r[1:])), r
  assert len({x for x in r}) > 2, r       # not collapsed onto the last char
  print("ok")
  EOF
  ```

### Step 8: Stem identification

- **Target:** `aligner.py: isolate_vocals(audio_path: str, output_dir: str) -> tuple[str, str]`.
- **Action:** First run the installed audio-separator once and note the exact output filename pattern (ground rule 6). Match on the stem marker it appends (expected `(Vocals)` / `(Instrumental)`), not on the whole filename. Remove the positional `output_files[0]`/`[1]` fallback. Remove the silent default-model fallback; let the load error propagate.
- **Constraint:** Keep the model name and the return order `(vocal, instrumental)`.
- **Verify:** Copy a short audio file to `my vocal instrumental test.wav`, run `isolate_vocals` on it, and confirm the two returned paths differ and point at the correct stems.

### Step 9: Romanization via a morphological analyzer (adds a dependency)

Skip or defer this step if a new dependency is not wanted; word spacing and `wa` will stay unreliable.

- **Target:** `japanese_utils.py: get_morae_for_text(text: str, k=None) -> list[dict]`, `convert_tokens_to_morae`.
- **Action:**
  - Replace pykakasi tokenization with `fugashi` + `unidic-lite` (or `SudachiPy` + `sudachidict_core`). Take the reading from the analyzer and convert katakana readings to hiragana before the existing mora splitter.
  - Drive rules from part of speech: particle `は` → `wa`; particle `へ` → `e`; auxiliaries (助動詞), conjunctive particles (接続助詞) and suffixes (接尾辞) set `is_token_end = False` on the preceding token.
  - Render `ー` by repeating the previous mora's vowel.
  - Delete `_ATTACHED_SUFFIXES`, `_OVERRIDES`, the small-kana mend pre-pass, and all in-place mutation of the input.
  - Keep the `k` parameter accepted but ignored so callers do not change, then remove `pykakasi` imports from `aligner.py`, `fast_lyrics.py`, `ass_compiler.py` and from `requirements.txt` once nothing uses it.
- **Constraint:** Output dict keys stay `orig`, `mora`, `rom`, `token_idx`, `is_token_end`. `_KANA_MORA_MAP` and the sokuon gemination pass stay unchanged. `orig` must still concatenate (whitespace aside) to the input text, because Step 7's mapping depends on it.
- **Verify:**
  ```
  python - <<'EOF'
  from japanese_utils import get_morae_for_text as g
  r = lambda s: "".join(m["rom"] + (" " if m["is_token_end"] else "") for m in g(s)).strip()
  for s, want in [("食べたい", "tabetai"), ("それは", "sore wa"), ("きっと", "kitto"),
                  ("ゲーム", "geemu"), ("眠った", "nemutta"), ("東京へ行く", "toukyou e iku")]:
      got = r(s); print(s, got); assert got == want, (s, got, want)
  EOF
  ```

### Step 10: Regression tests

- **Target:** New `tests/test_core.py` only.
- **Action:** Use pytest. Cover:
  - `get_morae_for_text`: the cases from Step 9's verification (if Step 9 was skipped, only `きっと` → `kitto` and `眠った` → `nemutta`).
  - `parse_lrc_text`: mixed enhanced and standard lines; two lines 0.1 s apart; credit lines skipped.
  - `_line_is_plausible`: accepts a normal line; rejects 2 s per mora; rejects a start 5 s away from guide plus offset.
  - `_map_tokens_to_times`: equal lengths; mismatched lengths; result is monotonic.
  - `_shift_line`: morae shift with the line; the input object is unchanged.
  - `_build_romaji_payload`: sum of all `\k` and `\kf` values equals `(last mora end - event start)` within 1 cs.
  - `_safe_filename`: no forbidden characters in the result.
- **Constraint:** No test may import `stable_whisper`, `whisper`, `torch` or `yt_dlp` at module level, or call `syncedlyrics`. If importing `aligner` or `main` pulls these in at import time, move those imports inside the functions that use them rather than mocking. Do not otherwise modify production code in this step; if a test exposes a bug, report it.
- **Verify:** `pytest -q tests/` passes with the network disconnected.

### Step 11: Docs, requirements, untrack artifacts

- **Target:** `README.md`, `CLAUDE.md`, `requirements.txt`, `.gitignore`.
- **Action:**
  - Update usage examples to the Step 2 CLI. Remove the "Windows Interactive Desktop Bridge" feature text and the `_launch_mpv` one-liner from CLAUDE.md.
  - Add ffmpeg to prerequisites.
  - Remove `pydantic` and `pyyaml` from `requirements.txt`; add the Step 9 packages if that step was done; add `pytest` as a dev note.
  - Replace the `!downloads/*.lrc` rule with `downloads/` and add `output/`. Run `git rm -r --cached output downloads`.
- **Constraint:** Do not rewrite sections of CLAUDE.md that describe still-open problems (intra-word mora timing, high-BPM tracks).
- **Verify:** `git ls-files output downloads` prints nothing. Every command in README.md's Usage block runs past argument parsing.

---

## Acceptance check after all steps

Run the three songs already used during development with `--no-play` and compare against the old files in git history:

1. No `\kf` value above 150 in any line.
2. No run of four or more consecutive `{\kf5}` tags at the end of a line.
3. `rerulili - Brain Fluid Explosion Girl`: first event starts near 0:00:18.5 (video has an 11.6 s intro relative to the LRC).
4. Romanization spot check: no single-mora fragments split off a verb stem (`tabeta i`, `awa sete`).
