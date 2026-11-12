"""
japanese_utils.py: Japanese lyric romanization and mora segmentation.
- Readings and parts of speech come from a morphological analyzer (fugashi + unidic-lite).
- Sokuon (っ / ッ) is geminated to the succeeding consonant (kitto, nemutta), never 'tsu'.
- Particles は / へ are romanized 'wa' / 'e'.
- Auxiliaries, conjunctive particles and suffixes attach to the preceding word without a space.
- The long-vowel mark ー repeats the previous mora's vowel.
"""

import re

_SMALL_KANA = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")

_KANA_MORA_MAP = {
    # Vowels
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    # K
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    # S
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    # T
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    # N
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    # H
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    # M
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    # Y
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    # R
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    # W / N
    "わ": "wa", "ゐ": "wi", "ゑ": "we", "を": "wo", "ん": "n",
    "ワ": "wa", "ヰ": "wi", "ヱ": "we", "ヲ": "wo", "ン": "n",
    # G
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    # Z
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    # D
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    # B
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    # P
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    # Contracted (yōon)
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "シャ": "sha", "シュ": "shu", "ショ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "チャ": "cha", "チュ": "chu", "チョ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "リャ": "rya", "リュ": "ryu", "リョ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ジャ": "ja", "ジュ": "ju", "ジョ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo",
    # Foreign / loanword sounds
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo",
    "ファ": "fa", "フィ": "fi", "フェ": "fe", "フォ": "fo",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du",
    "ティ": "ti", "ディ": "di", "トゥ": "tu", "ドゥ": "du",
    "うぃ": "wi", "うぇ": "we", "うぉ": "wo",
    "ウィ": "wi", "ウェ": "we", "ウォ": "wo",
    "ちぇ": "che", "じぇ": "je", "しぇ": "she",
    "チェ": "che", "ジェ": "je", "シェ": "she",
    # Standalone small vowels and symbols
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ゎ": "wa", "ヮ": "wa",
    "ー": "-",
}

_TAGGER = None


def _get_tagger():
    global _TAGGER
    if _TAGGER is None:
        import fugashi

        _TAGGER = fugashi.Tagger()
    return _TAGGER


def _katakana_to_hiragana(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def _tokenize(text: str) -> list[dict]:
    """
    Split text into word tokens: {"orig", "hira", "pos1", "pos2"}.
    Punctuation-only pieces are merged into a neighbouring token's "orig", so the "orig" values
    concatenate (whitespace aside) to the input text.
    """
    tokens: list[dict] = []
    pending = ""
    for chunk in text.split():
        if all(ord(c) < 128 for c in chunk):
            pieces = [{"orig": chunk, "hira": "", "pos1": "", "pos2": ""}]
        else:
            pieces = []
            for w in _get_tagger()(chunk):
                feat = w.feature
                kana = getattr(feat, "kana", None)
                if not kana or kana == "*":
                    kana = w.surface if re.fullmatch(r"[ぁ-ゖァ-ヶー]+", w.surface) else ""
                pieces.append({
                    "orig": w.surface,
                    "hira": _katakana_to_hiragana(kana),
                    "pos1": getattr(feat, "pos1", "") or "",
                    "pos2": getattr(feat, "pos2", "") or "",
                })
        if pieces:
            pieces[0]["start"] = True
        for piece in pieces:
            if not any(c.isalnum() for c in piece["orig"]):
                if tokens:
                    tokens[-1]["orig"] += piece["orig"]
                else:
                    pending += piece["orig"]
                continue
            piece["orig"] = pending + piece["orig"]
            pending = ""
            tokens.append(piece)
    return tokens


def convert_tokens_to_morae(conv_tokens: list[dict]) -> list[dict]:
    """
    Convert tokens ({"orig", "hira", "pos1", "pos2"}) into individual morae with Hepburn romaji.
    - Sokuon (っ / ッ) is converted to the geminated consonant of the succeeding mora (never 'tsu').
    - Particle は -> 'wa', particle へ -> 'e'.
    - ー repeats the previous mora's vowel.
    - Auxiliaries, conjunctive particles and suffixes do not start a new word (no space before them).
    The input tokens are not modified.
    """
    raw_morae: list[dict] = []
    attach_tokens: set[int] = set()
    for t_idx, t in enumerate(conv_tokens):
        orig = t.get("orig", "").strip()
        hira = t.get("hira", "").strip()
        pos1 = t.get("pos1", "")
        pos2 = t.get("pos2", "")
        if not orig:
            continue

        # ASCII / Latin words: split by whitespace so each word highlights as a unit
        if all(ord(c) < 128 for c in orig):
            for w in orig.split():
                clean_w = w.strip(".,!?\"'()[]{}~…")
                if clean_w:
                    raw_morae.append({
                        "orig": w,
                        "mora": clean_w,
                        "rom": clean_w,
                        "token_idx": t_idx,
                        "is_token_end": True,
                        "is_sokuon": False,
                    })
            continue

        if not t.get("start") and (pos1 in ("助動詞", "接尾辞") or pos2 == "接続助詞" or (hira != "" and set(hira) == {"ー"})):
            attach_tokens.add(t_idx)

        chars = [c for c in hira if not c.isspace() and c not in "、。・！？…〜~\"'()[]{}"]
        if not chars:
            # No reading available (Latin word next to Japanese punctuation, digits, unknown words):
            # keep the word as a single unit instead of dropping it.
            clean = "".join(c for c in orig if c.isalnum())
            if clean:
                raw_morae.append({
                    "orig": orig,
                    "mora": clean,
                    "rom": clean,
                    "token_idx": t_idx,
                    "is_token_end": True,
                    "is_sokuon": False,
                })
            continue
        token_morae = []
        i = 0
        while i < len(chars):
            if i + 1 < len(chars) and chars[i + 1] in _SMALL_KANA:
                compound = chars[i] + chars[i + 1]
                if compound in _KANA_MORA_MAP:
                    token_morae.append(compound)
                else:
                    token_morae.append(chars[i])
                    token_morae.append(chars[i + 1])
                i += 2
            else:
                token_morae.append(chars[i])
                i += 1

        for m_idx, m in enumerate(token_morae):
            is_end = (m_idx == len(token_morae) - 1)
            is_sokuon = (m in ("っ", "ッ"))

            rom = None if is_sokuon else _KANA_MORA_MAP.get(m, m)
            if pos1 == "助詞" and len(token_morae) == 1:
                if m == "は":
                    rom = "wa"
                elif m == "へ":
                    rom = "e"

            # If token ends in sokuon, it attaches to the next token without a space
            if is_end and is_sokuon:
                is_end = False

            raw_morae.append({
                "orig": orig,
                "mora": m,
                "rom": rom,
                "token_idx": t_idx,
                "is_token_end": is_end,
                "is_sokuon": is_sokuon,
            })

    # Pass 2: attached tokens (auxiliaries, conjunctive particles, suffixes) join the preceding word
    for idx in range(1, len(raw_morae)):
        cur = raw_morae[idx]
        prev = raw_morae[idx - 1]
        if cur["token_idx"] in attach_tokens and prev["token_idx"] != cur["token_idx"]:
            prev["is_token_end"] = False

    # Pass 3: resolve sokuon gemination by looking ahead to the next mora
    for idx, item in enumerate(raw_morae):
        if item["rom"] is None or item["is_sokuon"]:
            next_rom = ""
            for future in raw_morae[idx + 1:]:
                if future["rom"] and not future["is_sokuon"]:
                    next_rom = future["rom"]
                    break
            if next_rom.startswith("ch"):
                gem = "t"
            elif next_rom.startswith("sh"):
                gem = "s"
            elif next_rom.startswith("ts"):
                gem = "t"
            elif next_rom and next_rom[0].isalpha() and next_rom[0] not in "aeiou":
                gem = next_rom[0]
            else:
                gem = ""
            item["rom"] = gem

    # Pass 4: the long-vowel mark repeats the previous mora's vowel
    for idx, item in enumerate(raw_morae):
        if item["mora"] == "ー":
            prev_rom = raw_morae[idx - 1]["rom"] if idx > 0 else ""
            item["rom"] = prev_rom[-1] if prev_rom and prev_rom[-1] in "aeiou" else ""

    return raw_morae


def get_morae_for_text(text: str, k=None) -> list[dict]:
    """Tokenize and return list of morae with accurate romaji and word boundary markers. `k` is ignored."""
    return convert_tokens_to_morae(_tokenize(text))
