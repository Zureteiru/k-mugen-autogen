import re
import pykakasi
import syncedlyrics

from japanese_utils import convert_tokens_to_morae, get_morae_for_text
from models import LyricLine, MoraTiming


def _parse_timestamp(ts_str: str) -> float:
    """Parse [mm:ss.xx] or <mm:ss.xx> timestamp into seconds as float."""
    parts = ts_str.split(":")
    return int(parts[0]) * 60.0 + float(parts[1])


def _is_credit_or_meta(text: str) -> bool:
    """Detect whether a line is LRC metadata or credit rather than sung lyric."""
    clean = text.strip()
    if not clean:
        return True
    if re.match(r"^\[[a-zA-Z]+:", clean):
        return True
    # Strip any brackets
    raw = re.sub(r"\[\d{1,2}:\d{2}(?:\.\d+)?\]", "", clean).strip()
    raw = re.sub(r"<\d{1,2}:\d{2}(?:\.\d+)?>", "", raw).strip()
    if not raw:
        return True

    # Check if the line has any actual speech/lyric content (kana, kanji, or alphanumeric)
    has_text = any(
        c.isalnum() or ("\u3040" <= c <= "\u30ff") or ("\u4e00" <= c <= "\u9fff")
        for c in raw
    )
    if not has_text:
        return True

    credits = (
        "作词",
        "作曲",
        "编曲",
        "作詞",
        "作曲",
        "編曲",
        "歌：",
        "演唱：",
        "Lyrics by",
        "Music by",
        "Written by",
        "Arranged by",
        "Produced by",
    )
    for c in credits:
        if raw.startswith(c) or f"{c}:" in raw or f"{c} :" in raw:
            return True
    return False


def _parse_lrc(lrc_text: str, k: pykakasi.kakasi) -> list[LyricLine]:
    """Parse LRC text into LyricLine objects; each line is word-timed or line-timed on its own."""
    lrc_text = (
        lrc_text.replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
    )
    raw_lines = [line.strip() for line in lrc_text.splitlines() if line.strip()]

    # (start_sec, content, has_word_tags)
    entries: list[tuple[float, str, bool]] = []
    for line in raw_lines:
        if re.match(r"^\[[a-zA-Z]+:", line):
            continue
        if re.search(r"<\d{1,2}:\d{2}(?:\.\d+)?>", line):
            m = re.match(r"^\[(\d{1,2}:\d{2}(?:\.\d+)?)\](.*)", line)
            if m:
                entries.append((_parse_timestamp(m.group(1)), m.group(2).strip(), True))
            else:
                first_ts_m = re.search(r"<(\d{1,2}:\d{2}(?:\.\d+)?)>", line)
                if first_ts_m:
                    entries.append((_parse_timestamp(first_ts_m.group(1)), line, True))
            continue
        ts_matches = list(re.finditer(r"\[(\d{1,2}:\d{2}(?:\.\d+)?)\]", line))
        if not ts_matches:
            continue
        text = re.sub(r"\[\d{1,2}:\d{2}(?:\.\d+)?\]", "", line).strip()
        for m in ts_matches:
            entries.append((_parse_timestamp(m.group(1)), text, False))

    entries.sort(key=lambda x: x[0])

    lyric_lines: list[LyricLine] = []
    for idx, (current_start, content, has_word_tags) in enumerate(entries):
        if has_word_tags:
            next_start = entries[idx + 1][0] if idx + 1 < len(entries) else None
            matches = list(re.finditer(r"<(\d{1,2}:\d{2}(?:\.\d+)?)>([^<]*)", content))
            if not matches:
                continue

            raw_tokens = []
            for m in matches:
                ts = _parse_timestamp(m.group(1))
                txt = m.group(2).strip()
                raw_tokens.append((ts, txt))

            words_timed = []
            for j in range(len(raw_tokens)):
                ts, txt = raw_tokens[j]
                if not txt:
                    continue
                if j + 1 < len(raw_tokens):
                    end_ts = raw_tokens[j + 1][0]
                elif next_start and next_start > ts:
                    end_ts = min(next_start, ts + 2.0)
                else:
                    end_ts = ts + 0.5
                words_timed.append((txt, ts, end_ts))

            if not words_timed:
                continue

            orig_text = re.sub(r"<\d{1,2}:\d{2}(?:\.\d+)?>", "", content).strip()
            if _is_credit_or_meta(orig_text):
                continue

            morae_list: list[MoraTiming] = []
            for txt, w_start, w_end in words_timed:
                conv = k.convert(txt)
                morae_data = convert_tokens_to_morae(conv)
                m_count = max(1, len(morae_data))
                m_dur = max(0.08, w_end - w_start) / m_count
                for m_i, m in enumerate(morae_data):
                    m_s = w_start + m_i * m_dur
                    m_e = w_start + (m_i + 1) * m_dur
                    rom = m["rom"] + (" " if m["is_token_end"] else "")
                    morae_list.append(
                        MoraTiming(
                            hiragana=m["mora"],
                            romaji=rom,
                            start_sec=round(m_s, 3),
                            end_sec=round(m_e, 3),
                        )
                    )

            if morae_list:
                lyric_lines.append(
                    LyricLine(
                        original_text=orig_text,
                        start_sec=morae_list[0].start_sec,
                        end_sec=morae_list[-1].end_sec,
                        morae=morae_list,
                    )
                )
            continue

        text = content
        if _is_credit_or_meta(text):
            continue

        morae_tokens = get_morae_for_text(text, k)
        if not morae_tokens:
            continue

        # Next timestamp in the LRC defines line duration
        next_start = None
        for next_idx in range(idx + 1, len(entries)):
            if entries[next_idx][0] > current_start:
                next_start = entries[next_idx][0]
                break

        mora_count = len(morae_tokens)
        natural_duration = mora_count * 0.32
        if next_start is not None and next_start > current_start:
            available_time = next_start - current_start
            duration = max(0.3, min(available_time - 0.2, max(2.0, natural_duration)))
        else:
            duration = max(2.5, natural_duration)

        mora_duration = duration / mora_count
        mora_timings: list[MoraTiming] = []

        for m_idx, m in enumerate(morae_tokens):
            m_s = current_start + m_idx * mora_duration
            m_e = current_start + (m_idx + 1) * mora_duration
            mora_timings.append(
                MoraTiming(
                    hiragana=m["mora"],
                    romaji=m["rom"] + (" " if m["is_token_end"] else ""),
                    start_sec=round(m_s, 3),
                    end_sec=round(m_e, 3),
                )
            )

        lyric_lines.append(
            LyricLine(
                original_text=text,
                start_sec=round(current_start, 3),
                end_sec=round(current_start + duration, 3),
                morae=mora_timings,
            )
        )

    return lyric_lines


def fetch_and_parse_lyrics(artist: str, title: str) -> tuple[str, list[LyricLine] | None] | None:
    """
    Fetch lyrics using syncedlyrics.
    Returns (lyrics_text, parsed_lines); parsed_lines is None when the lyrics have no timestamps.
    """
    k = pykakasi.kakasi()
    query = f"{artist} {title}".strip()

    # 1. Try enhanced word-synced search first
    lrc_text = syncedlyrics.search(query, enhanced=True, providers=["netease", "lrclib"])

    # 2. Fall back to standard line-synced search
    if not lrc_text:
        lrc_text = syncedlyrics.search(query, providers=["netease", "lrclib"])

    if not lrc_text:
        return None

    if not re.search(r"\[\d{1,2}:\d{2}", lrc_text):
        return lrc_text.strip(), None

    parsed = _parse_lrc(lrc_text, k)
    if not parsed:
        return None
    return "\n".join(l.original_text for l in parsed), parsed


def parse_lrc_text(lrc_text: str, k: pykakasi.kakasi | None = None) -> list[LyricLine]:
    """Parse raw LRC text string into a list of LyricLine objects."""
    if k is None:
        from japanese_utils import get_kakasi
        k = get_kakasi()
    return _parse_lrc(lrc_text, k)

