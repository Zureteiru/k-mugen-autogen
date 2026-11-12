import dataclasses
import logging
import os
import re
import statistics

from japanese_utils import get_morae_for_text
from models import LyricLine, MoraTiming

logger = logging.getLogger(__name__)


def _get_device() -> str:
    """Check CUDA availability and return appropriate torch device string with logging."""
    try:
        import torch

        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"CUDA is available. Using GPU: {gpu_name}")
            return "cuda"
        else:
            logger.info("CUDA is unavailable. Falling back to CPU.")
            return "cpu"
    except ImportError:
        logger.warning("torch is not installed. Defaulting to CPU.")
        return "cpu"
    except Exception as e:
        logger.warning(f"Error checking CUDA status ({e}). Defaulting to CPU.")
        return "cpu"


def isolate_vocals(audio_path: str, output_dir: str) -> tuple[str, str]:
    """
    Separate an audio file into vocal and instrumental stems using audio_separator.
    Uses 'UVR-MDX-NET-Inst_HQ_3.onnx' model.
    Returns (vocal_path, instrumental_path).
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Starting vocal isolation for: {audio_path}")
    logger.info(f"Target stem directory: {output_dir}")

    try:
        from audio_separator.separator import Separator
    except ImportError as e:
        logger.error(
            "audio-separator is required for stem separation. "
            "Install it via: pip install 'audio-separator[cpu]' or 'audio-separator[gpu]'"
        )
        raise e

    model_name = "UVR-MDX-NET-Inst_HQ_3.onnx"
    logger.info(f"Initializing Separator with model: {model_name}")

    separator = Separator(output_dir=output_dir)
    separator.load_model(model_filename=model_name)

    logger.info("Running stem separation...")
    output_files = separator.separate(audio_path)
    logger.info(f"Separation produced {len(output_files)} files: {output_files}")

    vocal_path = None
    inst_path = None

    for fname in output_files:
        full_path = os.path.join(output_dir, fname) if not os.path.isabs(fname) else fname
        # audio-separator names stems "<input>_(Vocals)_<model>.wav" / "<input>_(Instrumental)_<model>.wav";
        # the last marker is the stem, since the input name may contain markers or words like "vocal".
        markers = re.findall(r"\((Vocals|Instrumental)\)", os.path.basename(fname))
        if not markers:
            continue
        if markers[-1] == "Vocals":
            vocal_path = full_path
        else:
            inst_path = full_path

    if not vocal_path or not inst_path:
        raise RuntimeError(f"Failed to isolate stems from {audio_path}. Generated files: {output_files}")

    logger.info(f"Vocal stem: {vocal_path}")
    logger.info(f"Instrumental stem: {inst_path}")
    return vocal_path, inst_path


def _align_global(model, audio, lines: list[str], lang: str) -> list[list | None]:
    """Run one forced alignment over all lines; one word list per input line, None when missing."""
    res = model.align(audio, "\n".join(lines), language=lang, original_split=True)
    if not res or not hasattr(res, "segments") or len(res.segments) != len(lines):
        return [None] * len(lines)
    out: list[list | None] = []
    for seg in res.segments:
        words = [w for w in getattr(seg, "words", []) if getattr(w, "word", "").strip()]
        out.append(words or None)
    return out


def _line_is_plausible(
    words: list,
    n_morae: int,
    prev_end: float,
    guide: LyricLine | None,
    offset: float,
) -> bool:
    """Accept a line's aligned words only if their pace, order and (optional) guide position make sense."""
    if not words:
        return False
    start = words[0].start
    end = words[-1].end
    if not 0.04 <= (end - start) / max(1, n_morae) <= 1.5:
        return False
    if start < prev_end - 0.1:
        return False
    if guide is not None and abs(start - (guide.start_sec + offset)) >= 3.0:
        return False
    return True


def _align_window(model, audio, text: str, t0: float, t1: float, lang: str) -> list | None:
    """Align one line of text inside audio[t0:t1] and return its words in absolute time."""
    sr = 16000
    t0 = max(0.0, t0)
    s0 = int(round(t0 * sr))
    s1 = min(len(audio), int(round(t1 * sr)))
    if s1 <= s0:
        return None
    try:
        res = model.align(audio[s0:s1], text, language=lang)
    except Exception as e:
        logger.warning(f"Window alignment failed for line '{text}' ({e})")
        return None

    words = []
    if res and res.segments and res.segments[0].words:
        for w in res.segments[0].words:
            if getattr(w, "word", "").strip():
                w.start += t0
                w.end += t0
                words.append(w)

    # Re-align dropped trailing words of English lines
    expected_words = text.split()
    if lang != "ja" and 0 < len(words) < len(expected_words):
        aligned_chars = sum(len(w.word.strip()) for w in words)
        expected_chars = sum(len(w) for w in expected_words)
        if aligned_chars < expected_chars * 0.8:
            rem_text = " ".join(expected_words[len(words):])
            new_t0 = words[-1].end
            if t1 > new_t0 + 0.2:
                more = _align_window(model, audio, rem_text, new_t0, t1, "en")
                if more:
                    words.extend(more)

    return words or None


def _shift_line(line: LyricLine, offset: float) -> LyricLine:
    """Return a copy of line with its start, end and every mora shifted by offset seconds."""
    return dataclasses.replace(
        line,
        start_sec=line.start_sec + offset,
        end_sec=line.end_sec + offset,
        morae=[
            dataclasses.replace(m, start_sec=m.start_sec + offset, end_sec=m.end_sec + offset)
            for m in line.morae
        ],
    )


def _map_tokens_to_times(whisper_chars: list[dict], token_lens: list[int]) -> list[tuple[float, float]]:
    """Map each token (of token_lens characters) onto the Whisper characters; returns (start, end) per token."""
    W = len(whisper_chars)
    T = sum(token_lens)
    if W == 0 or T == 0:
        return []

    spans: list[tuple[float, float]] = []
    pos = 0
    for n in token_lens:
        if n <= 0:
            raise ValueError(f"token length must be positive, got {n}")
        if W == T:
            lo = pos
            hi = pos + n - 1
        else:
            lo = int(pos * W / T)
            hi = max(lo, int((pos + n) * W / T) - 1)
        spans.append((whisper_chars[lo]["start"], whisper_chars[hi]["end"]))
        pos += n
    return spans


def force_align_japanese(
    vocal_path: str,
    raw_lyrics_text: str,
    lrc_guide_lines: list[LyricLine] | None = None,
) -> list[LyricLine]:
    """
    Perform foolproof, tightly synchronized forced alignment of Japanese lyrics onto audio track.
    If lrc_guide_lines is provided, aligns line-by-line within each line's acoustic window,
    preventing any drift across guitar solos, instrumental breaks, or song intros.
    """
    if not os.path.exists(vocal_path):
        raise FileNotFoundError(f"Vocal track not found: {vocal_path}")

    raw_lines = [line.strip() for line in raw_lyrics_text.splitlines() if line.strip()]
    if not raw_lines:
        logger.warning("Empty lyrics provided for forced alignment.")
        return []

    try:
        import stable_whisper
        import whisper
    except ImportError as e:
        logger.error("stable-ts is required for forced alignment. Install it via: pip install stable-ts")
        raise e

    device = _get_device()
    logger.info(f"Loading stable_whisper 'base' model on device '{device}'...")
    try:
        model = stable_whisper.load_model("base", device=device)
    except Exception as e:
        if device != "cpu":
            logger.warning(f"Failed to load model on {device} ({e}). Retrying on CPU...")
            model = stable_whisper.load_model("base", device="cpu")
        else:
            raise e

    audio = whisper.load_audio(vocal_path)
    sr = 16000
    total_audio_sec = len(audio) / sr

    is_mostly_ja = any(
        ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
        for c in "\n".join(raw_lines)
    )
    global_lang = "ja" if is_mostly_ja else "en"

    logger.info("Running global forced alignment on audio file...")
    try:
        global_words = _align_global(model, audio, raw_lines, global_lang)
    except Exception as e:
        logger.warning(f"Global alignment attempt encountered error: {e}")
        global_words = [None] * len(raw_lines)

    guides = lrc_guide_lines if lrc_guide_lines and len(lrc_guide_lines) == len(raw_lines) else None
    offsets = [
        global_words[i][0].start - guides[i].start_sec
        for i in range(len(raw_lines))
        if guides and global_words[i]
    ]
    offset = statistics.median(offsets) if offsets else 0.0
    if guides:
        logger.info(f"LRC guide offset (median of global alignment): {offset:+.2f}s")

    lyric_lines: list[LyricLine] = []

    for line_idx, orig_line in enumerate(raw_lines):
        guide = guides[line_idx] if guides else None
        prev_end = lyric_lines[-1].end_sec if lyric_lines else 0.0
        n_morae = len(get_morae_for_text(orig_line))

        words = global_words[line_idx] or []
        if not _line_is_plausible(words, n_morae, prev_end, guide, offset):
            words = []
            if guide is not None:
                cleaned_text = re.sub(r"([.,!?;:…])([a-zA-Z])", r"\1 \2", orig_line)
                cleaned_text = (
                    cleaned_text.replace("“", '"')
                    .replace("”", '"')
                    .replace("’", "'")
                    .replace("‘", "'")
                )
                lang = "ja" if any(
                    ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
                    for c in cleaned_text
                ) else "en"
                g_end = guide.end_sec + offset
                next_start = (
                    guides[line_idx + 1].start_sec + offset
                    if line_idx + 1 < len(guides)
                    else g_end + 4.0
                )
                t0 = max(prev_end, guide.start_sec + offset - 0.35)
                t1 = min(total_audio_sec, max(g_end + 0.5, next_start - 0.05))
                if t1 <= t0 + 0.3:
                    t1 = min(total_audio_sec, t0 + 1.2)
                window_words = _align_window(model, audio, cleaned_text, t0, t1, lang)
                if window_words and _line_is_plausible(window_words, n_morae, prev_end, guide, offset):
                    words = window_words

        if not words:
            if guide:
                lyric_lines.append(_shift_line(guide, offset))
            else:
                prev_end = lyric_lines[-1].end_sec if lyric_lines else 0.0
                start_fallback = prev_end + 0.50
                morae_data = get_morae_for_text(orig_line)
                fallback_morae: list[MoraTiming] = []
                cur_t = start_fallback
                for m in morae_data:
                    m_end = cur_t + 0.28
                    fallback_morae.append(
                        MoraTiming(
                            hiragana=m["mora"],
                            romaji=m["rom"] + (" " if m["is_token_end"] else ""),
                            start_sec=round(cur_t, 3),
                            end_sec=round(m_end, 3),
                        )
                    )
                    cur_t = m_end
                lyric_lines.append(
                    LyricLine(
                        original_text=orig_line,
                        start_sec=round(start_fallback, 3),
                        end_sec=round(cur_t, 3),
                        morae=fallback_morae,
                    )
                )
            continue

        is_ja = any(
            ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
            for c in orig_line
        )

        line_mora_timings: list[MoraTiming] = []

        if not is_ja:
            # English / Latin text: map words directly to Whisper word timestamps
            orig_words = orig_line.split()
            for w_idx, w_orig in enumerate(orig_words):
                if w_idx < len(words):
                    w_wh = words[w_idx]
                    s = w_wh.start
                    e = max(s + 0.08, w_wh.end)
                else:
                    prev_e = line_mora_timings[-1].end_sec if line_mora_timings else words[-1].end
                    s = prev_e + 0.02
                    e = s + 0.25
                rom = w_orig + (" " if w_idx < len(orig_words) - 1 else "")
                line_mora_timings.append(
                    MoraTiming(
                        hiragana=w_orig,
                        romaji=rom,
                        start_sec=round(s, 3),
                        end_sec=round(e, 3),
                    )
                )
        else:
            # Japanese text: slice characters from Whisper words and align to morae
            whisper_chars: list[dict] = []
            for w in words:
                w_txt = "".join(w.word.split())
                n = len(w_txt)
                if n == 0:
                    continue
                dur = max(0.08, w.end - w.start)
                sub = dur / n
                for c_i, ch in enumerate(w_txt):
                    whisper_chars.append({
                        "char": ch,
                        "start": w.start + c_i * sub,
                        "end": w.start + (c_i + 1) * sub,
                    })

            morae_records = get_morae_for_text(orig_line)

            token_to_morae: dict[int, list[dict]] = {}
            for m in morae_records:
                token_to_morae.setdefault(m["token_idx"], []).append(m)

            tokens = [(t_idx, "".join(ms[0]["orig"].split())) for t_idx, ms in token_to_morae.items()]
            tokens = [(t_idx, t_orig) for t_idx, t_orig in tokens if t_orig]
            spans = _map_tokens_to_times(whisper_chars, [len(t_orig) for _, t_orig in tokens])
            for (t_idx, _), (t_start, t_end) in zip(tokens, spans):
                m_list = token_to_morae.get(t_idx, [])
                if not m_list:
                    continue

                m_count = len(m_list)
                m_dur = max(0.08, t_end - t_start) / m_count

                for m_i, m_item in enumerate(m_list):
                    m_h = m_item["mora"]
                    m_rom = m_item["rom"] + (" " if m_item["is_token_end"] else "")
                    m_s = t_start + m_i * m_dur
                    m_e = t_start + (m_i + 1) * m_dur

                    line_mora_timings.append(
                        MoraTiming(
                            hiragana=m_h,
                            romaji=m_rom,
                            start_sec=round(m_s, 3),
                            end_sec=round(m_e, 3),
                        )
                    )

        if any(b.start_sec < a.start_sec for a, b in zip(line_mora_timings, line_mora_timings[1:])):
            logger.warning(f"Mora start times are not non-decreasing in line: {orig_line}")

        if line_mora_timings:
            line_start = line_mora_timings[0].start_sec
            line_end = line_mora_timings[-1].end_sec
            lyric_lines.append(
                LyricLine(
                    original_text=orig_line,
                    start_sec=line_start,
                    end_sec=line_end,
                    morae=line_mora_timings,
                )
            )

    logger.info(f"Successfully reconstructed {len(lyric_lines)} LyricLine objects.")
    return lyric_lines
