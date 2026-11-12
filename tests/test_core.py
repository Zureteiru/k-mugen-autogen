import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aligner import _line_is_plausible, _map_tokens_to_times, _shift_line
from ass_compiler import _build_romaji_payload
from fast_lyrics import parse_lrc_text
from japanese_utils import get_morae_for_text
from main import _safe_filename
from models import LyricLine, MoraTiming


def _romaji(text: str) -> str:
    return "".join(m["rom"] + (" " if m["is_token_end"] else "") for m in get_morae_for_text(text)).strip()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("食べたい", "tabetai"),
        ("それは", "sore wa"),
        ("きっと", "kitto"),
        ("ゲーム", "geemu"),
        ("眠った", "nemutta"),
        ("東京へ行く", "toukyou e iku"),
    ],
)
def test_get_morae_for_text(text, expected):
    assert _romaji(text) == expected


def test_wa_only_for_particle_ha():
    assert _romaji("母は") == "haha wa"


def test_parse_lrc_text_mixed_enhanced_and_standard():
    lrc = "[00:01.00]<00:01.00>あ<00:01.50>い\n[00:03.00]うえ\n[00:05.00]おか"
    lines = parse_lrc_text(lrc)
    assert [l.original_text for l in lines] == ["あい", "うえ", "おか"]
    assert all(l.end_sec > l.start_sec for l in lines)
    assert all(m.end_sec > m.start_sec for l in lines for m in l.morae)


def test_parse_lrc_text_sorts_by_start_time():
    lines = parse_lrc_text("[00:05.00]おか\n[00:01.00]うえ")
    assert [l.original_text for l in lines] == ["うえ", "おか"]


def test_parse_lrc_text_lines_close_together():
    lines = parse_lrc_text("[00:03.00]うえ\n[00:03.10]おか")
    assert len(lines) == 2
    assert all(l.end_sec > l.start_sec for l in lines)
    assert all(m.end_sec > m.start_sec for l in lines for m in l.morae)


def test_parse_lrc_text_skips_credit_lines():
    lrc = "[ti:Title]\n[00:01.00]作曲：誰か\n[00:02.00]Lyrics by Someone\n[00:03.00]うえ"
    lines = parse_lrc_text(lrc)
    assert [l.original_text for l in lines] == ["うえ"]


def _words(start, end):
    return [SimpleNamespace(start=start, end=end, word="x")]


def _guide(start):
    return LyricLine("x", start, start + 2.0, [MoraTiming("あ", "a", start, start + 2.0)])


def test_line_is_plausible_accepts_normal_line():
    assert _line_is_plausible(_words(10.0, 12.0), 8, 9.0, None, 0.0)
    assert _line_is_plausible(_words(10.0, 12.0), 8, 9.0, _guide(9.5), 0.5)
    assert _line_is_plausible(_words(10.0, 12.0), 8, 9.0, _guide(5.0), 5.0)  # guide + offset matters


def test_line_is_plausible_rejects_slow_line():
    assert not _line_is_plausible(_words(10.0, 12.0), 1, 9.0, None, 0.0)  # 2 s per mora


def test_line_is_plausible_rejects_far_from_guide():
    assert not _line_is_plausible(_words(15.0, 17.0), 8, 9.0, _guide(9.0), 1.0)  # 5 s off guide + offset
    assert not _line_is_plausible(_words(10.0, 12.0), 8, 9.0, _guide(10.0), 5.0)  # offset pushes guide away


def test_line_is_plausible_rejects_start_before_previous_line():
    assert not _line_is_plausible(_words(8.0, 10.0), 8, 9.0, None, 0.0)


def _chars(n):
    return [{"start": float(i), "end": float(i + 1)} for i in range(n)]


def test_map_tokens_equal_lengths():
    spans = _map_tokens_to_times(_chars(6), [2, 1, 3])
    assert spans == [(0.0, 2.0), (2.0, 3.0), (3.0, 6.0)]


def test_map_tokens_mismatched_lengths_do_not_collapse():
    spans = _map_tokens_to_times(_chars(6), [2, 2, 2, 2, 2])
    assert spans == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 6.0)]


@pytest.mark.parametrize("w, lens", [(3, [2, 2, 2, 2]), (10, [1, 2]), (1, [3]), (7, [7])])
def test_map_tokens_is_monotonic(w, lens):
    spans = _map_tokens_to_times(_chars(w), lens)
    assert len(spans) == len(lens)
    assert all(b[0] >= a[0] and b[1] >= a[1] for a, b in zip(spans, spans[1:]))
    assert all(end > start for start, end in spans)
    assert spans[-1][1] == float(w)


def test_shift_line_shifts_everything_and_keeps_input():
    line = LyricLine("あい", 1.0, 2.0, [MoraTiming("あ", "a", 1.0, 1.5), MoraTiming("い", "i", 1.5, 2.0)])
    shifted = _shift_line(line, 2.5)
    assert (shifted.start_sec, shifted.end_sec) == (3.5, 4.5)
    assert [(m.start_sec, m.end_sec) for m in shifted.morae] == [(3.5, 4.0), (4.0, 4.5)]
    assert (line.start_sec, line.end_sec) == (1.0, 2.0)
    assert [(m.start_sec, m.end_sec) for m in line.morae] == [(1.0, 1.5), (1.5, 2.0)]
    assert shifted.morae[0] is not line.morae[0]


def test_build_romaji_payload_total_matches_line_duration():
    import re

    morae = [
        MoraTiming("あ", "a", 10.00, 10.31),
        MoraTiming("い", "i ", 10.31, 10.80),
        MoraTiming("う", "u", 11.40, 11.77),  # gap before this one
        MoraTiming("え", "e", 11.77, 12.13),
    ]
    line = LyricLine("あいうえ", 10.0, 12.13, morae)
    event_start = 9.5
    payload = _build_romaji_payload(line, event_start)
    total_cs = sum(int(n) for n in re.findall(r"\\k[f]?(\d+)", payload))
    expected_cs = round((morae[-1].end_sec - event_start) * 100)
    assert abs(total_cs - expected_cs) <= 1


@pytest.mark.parametrize("name", ['AC/DC: Who?', 'a<b>c|d*e"f\\g', "x\x00y\x1fz", "trail.. .", "../../etc/passwd", ""])
def test_safe_filename_has_no_forbidden_characters(name):
    result = _safe_filename(name)
    assert not any(c in result for c in '<>:"/\\|?*')
    assert not any(ord(c) < 32 for c in result)
    assert result == result.rstrip(". ")


# --- Karaoke Mugen (kara.moe) house style ---------------------------------------------------

KM_UP_STYLE = (
    "Style: Sample KM [Up],Arial,24,&H00008AFF,&H00FFFFFF,&H00000000,&H00000000,"
    "-1,0,0,0,100,100,0,0,1,1.5,0,8,2,2,20,1"
)


def _km_song(tmp_path):
    from ass_compiler import compile_ass

    lines = [
        LyricLine("あい", 0.4, 1.0, [MoraTiming("あ", "a", 0.4, 0.6), MoraTiming("い", "i ", 0.6, 1.0)]),
        LyricLine("うえ", 2.0, 3.8, [MoraTiming("う", "u", 2.0, 3.2), MoraTiming("え", "e", 3.2, 3.8)]),
        LyricLine("おか", 4.0, 5.0, [MoraTiming("お", "o", 4.0, 4.5), MoraTiming("か", "ka", 4.5, 5.0)]),
    ]
    content = compile_ass(lines, "T", str(tmp_path / "t.ass"))
    fx = [l for l in content.splitlines() if l.startswith("Dialogue:") and ",fx," in l]
    return content, fx


def test_km_header_style_and_template(tmp_path):
    content, _ = _km_song(tmp_path)
    assert KM_UP_STYLE in content.splitlines()
    assert "PlayResX: 0" in content and "PlayResY: 0" in content
    assert "ScaledBorderAndShadow: yes" in content
    assert any(l.startswith("Comment:") and "template pre-line all keeptags" in l for l in content.splitlines())
    assert sum(",karaoke," in l for l in content.splitlines()) == 3


def test_km_lead_in_fade_and_tail(tmp_path):
    _, fx = _km_song(tmp_path)
    # Normal line: appears 0.9 s early with \k90\fad(300,200), ends 0.2 s after the last syllable
    assert fx[1].startswith("Dialogue: 0,0:00:01.10,0:00:04.00,Sample KM [Up],")
    assert "fx,{\\k90\\fad(300,200)}" in fx[1]
    # Line starting before 0.9 s: lead and fade-in equal its start (template's $start < 900 branch)
    assert fx[0].startswith("Dialogue: 0,0:00:00.00,0:00:01.20,")
    assert "fx,{\\k40\\fad(400,200)}" in fx[0]


def test_km_k_vs_kf_and_overlap(tmp_path):
    _, fx = _km_song(tmp_path)
    assert "{\\k20}a{\\k40}i " in fx[0]  # short syllables: instant fill
    assert "{\\kf120}u" in fx[1]  # > 100 cs: progressive fill
    # Lines overlap (next line's lead-in starts before this one ends) so libass stacks them
    end_1 = fx[1].split(",")[2]
    start_2 = fx[2].split(",")[1]
    assert start_2 < end_1
