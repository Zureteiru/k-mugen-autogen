import logging
import os
import re
import types
import pykakasi

from japanese_utils import convert_tokens_to_morae, get_morae_for_text
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

    try:
        separator = Separator(output_dir=output_dir)
        separator.load_model(model_filename=model_name)
    except Exception as e:
        logger.warning(f"Failed to load {model_name} ({e}). Attempting default separation model...")
        separator = Separator(output_dir=output_dir)
        separator.load_model()

    logger.info("Running stem separation...")
    output_files = separator.separate(audio_path)
    logger.info(f"Separation produced {len(output_files)} files: {output_files}")

    vocal_path = None
    inst_path = None

    for fname in output_files:
        full_path = os.path.join(output_dir, fname) if not os.path.isabs(fname) else fname
        lower_name = fname.lower()
        if "vocal" in lower_name:
            vocal_path = full_path
        elif "inst" in lower_name or "instrumental" in lower_name:
            inst_path = full_path

    # Fallbacks if file naming differs
    if not vocal_path and output_files:
        vocal_path = os.path.join(output_dir, output_files[0]) if not os.path.isabs(output_files[0]) else output_files[0]
    if not inst_path and len(output_files) > 1:
        inst_path = os.path.join(output_dir, output_files[1]) if not os.path.isabs(output_files[1]) else output_files[1]

    if not vocal_path or not inst_path:
        raise RuntimeError(f"Failed to isolate stems from {audio_path}. Generated files: {output_files}")

    logger.info(f"Vocal stem: {vocal_path}")
    logger.info(f"Instrumental stem: {inst_path}")
    return vocal_path, inst_path


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

    k = pykakasi.kakasi()

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

    segments: list = []
    # Step 1: Try global forced alignment first across the entire audio track
    logger.info("Attempting global forced alignment on audio file...")
    lyrics_payload = "\n".join(raw_lines)
    is_mostly_ja = any(
        ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
        for c in lyrics_payload
    )
    global_lang = "ja" if is_mostly_ja else "en"

    try:
        global_res = model.align(vocal_path, lyrics_payload, language=global_lang, original_split=True)
        if global_res and hasattr(global_res, "segments") and len(global_res.segments) == len(raw_lines):
            aligned_count = sum(
                1 for seg in global_res.segments
                if [w for w in getattr(seg, "words", []) if getattr(w, "word", "").strip()]
            )
            if aligned_count >= len(raw_lines) * 0.85:
                logger.info(f"Global alignment succeeded with high coverage ({aligned_count}/{len(raw_lines)} lines).")
                segments = global_res.segments
    except Exception as e:
        logger.warning(f"Global alignment attempt encountered error: {e}")

    # Step 2: Fall back to anchored slice alignment if global alignment had low coverage
    if not segments and lrc_guide_lines and len(lrc_guide_lines) == len(raw_lines):
        logger.info("Using LRC guide windows for anchored line-by-line Whisper alignment...")
        audio = whisper.load_audio(vocal_path)
        sr = 16000
        total_audio_sec = len(audio) / sr
        last_aligned_end = 0.0

        # Automatic LRC offset probe to detect video intro length mismatches
        try:
            probe_slice = audio[: int(min(total_audio_sec, 60.0) * sr)]
            probe_res = model.align(probe_slice, lrc_guide_lines[0].original_text, language=global_lang)
            if probe_res and probe_res.segments and probe_res.segments[0].words:
                actual_start = probe_res.segments[0].words[0].start
                guide_start = lrc_guide_lines[0].start_sec
                offset = actual_start - guide_start
                if abs(offset) > 1.2:
                    logger.info(f"Detected global LRC offset of {offset:+.2f}s! Shifting guide windows...")
                    for g in lrc_guide_lines:
                        g.start_sec = max(0.0, g.start_sec + offset)
                        g.end_sec = max(0.0, g.end_sec + offset)
        except Exception as e:
            logger.warning(f"Offset probe skipped: {e}")

        for idx, lrc_line in enumerate(lrc_guide_lines):
            orig_text = lrc_line.original_text.strip()
            # Clean punctuation spacing and quotes
            cleaned_text = re.sub(r"([.,!?;:…])([a-zA-Z])", r"\1 \2", orig_text)
            cleaned_text = (
                cleaned_text.replace("“", '"')
                .replace("”", '"')
                .replace("’", "'")
                .replace("‘", "'")
            )

            is_ja = any(
                ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
                for c in cleaned_text
            )
            lang = "ja" if is_ja else "en"

            next_start = (
                lrc_guide_lines[idx + 1].start_sec
                if idx + 1 < len(lrc_guide_lines)
                else lrc_line.end_sec + 4.0
            )
            t0 = max(last_aligned_end, lrc_line.start_sec - 0.35)
            t1 = min(total_audio_sec, max(lrc_line.end_sec + 0.5, next_start - 0.05))
            if t1 <= t0 + 0.3:
                t1 = min(total_audio_sec, t0 + 1.2)

            s0 = int(round(t0 * sr))
            s1 = int(round(t1 * sr))
            slice_audio = audio[s0:s1]

            try:
                res = model.align(slice_audio, cleaned_text, language=lang)
                words = []
                if res and res.segments and res.segments[0].words:
                    for w in res.segments[0].words:
                        if getattr(w, "word", "").strip():
                            w.start += t0
                            w.end += t0
                            words.append(w)

                # Check if multi-pass alignment is needed for dropped trailing words
                expected_words = cleaned_text.split()
                if not is_ja and 0 < len(words) < len(expected_words):
                    aligned_chars = sum(len(w.word.strip()) for w in words)
                    expected_chars = sum(len(w) for w in expected_words)
                    if aligned_chars < expected_chars * 0.8:
                        rem_text = " ".join(expected_words[len(words):])
                        new_t0 = words[-1].end
                        if t1 > new_t0 + 0.2:
                            new_s0 = int(round(new_t0 * sr))
                            slice2 = audio[new_s0:s1]
                            try:
                                res2 = model.align(slice2, rem_text, language="en")
                                if res2 and res2.segments and res2.segments[0].words:
                                    for w2 in res2.segments[0].words:
                                        if getattr(w2, "word", "").strip():
                                            w2.start += new_t0
                                            w2.end += new_t0
                                            words.append(w2)
                            except Exception:
                                pass

                if words:
                    last_aligned_end = words[-1].end
                    seg_obj = types.SimpleNamespace(words=words)
                    segments.append(seg_obj)
                else:
                    last_aligned_end = lrc_line.end_sec
                    segments.append(None)
            except Exception as e:
                logger.warning(f"Slice alignment failed for line '{orig_text}' ({e})")
                last_aligned_end = lrc_line.end_sec
                segments.append(None)

    logger.info(f"Received {len(segments)} segments from stable_whisper.")

    lyric_lines: list[LyricLine] = []

    for line_idx, orig_line in enumerate(raw_lines):
        words = []
        if line_idx < len(segments) and segments[line_idx] is not None:
            seg = segments[line_idx]
            words = [w for w in getattr(seg, "words", []) if getattr(w, "word", "").strip()]

        guide = lrc_guide_lines[line_idx] if (lrc_guide_lines and line_idx < len(lrc_guide_lines)) else None

        if not words:
            if guide:
                lyric_lines.append(guide)
            else:
                prev_end = lyric_lines[-1].end_sec if lyric_lines else 0.0
                start_fallback = prev_end + 0.50
                morae_data = get_morae_for_text(orig_line, k)
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

        # Detect intra-line anomalous gaps (> 2.0s silence)
        for j in range(1, len(words)):
            gap = words[j].start - words[j - 1].end
            if gap > 2.0:
                words[j].start = words[j - 1].end
                w_dur = max(0.25, len(words[j].word.strip()) * 0.25)
                words[j].end = words[j].start + w_dur

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
            # Japanese text: slice characters from Whisper words and align to pykakasi morae
            whisper_chars: list[dict] = []
            for w in words:
                w_txt = w.word.strip()
                n = len(w_txt)
                dur = max(0.08, w.end - w.start)
                sub = dur / n
                for c_i, ch in enumerate(w_txt):
                    whisper_chars.append({
                        "char": ch,
                        "start": w.start + c_i * sub,
                        "end": w.start + (c_i + 1) * sub,
                    })

            conv = k.convert(orig_line)
            morae_records = convert_tokens_to_morae(conv)

            token_to_morae: dict[int, list[dict]] = {}
            for m in morae_records:
                token_to_morae.setdefault(m["token_idx"], []).append(m)

            char_pos = 0
            for t_idx, t in enumerate(conv):
                t_orig = t.get("orig", "").strip()
                if not t_orig:
                    continue

                c_len = len(t_orig)
                c_start_idx = min(len(whisper_chars) - 1, char_pos)
                c_end_idx = min(len(whisper_chars) - 1, char_pos + c_len - 1)
                char_pos += c_len

                t_start = whisper_chars[c_start_idx]["start"]
                t_end = whisper_chars[c_end_idx]["end"]

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
