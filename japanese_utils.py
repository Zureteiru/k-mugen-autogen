"""
japanese_utils.py: Robust Japanese lyric romanization and mora segmentation.
Fixes:
- Sokuon (っ / ッ) is geminated to succeeding consonant (e.g. kitto, nemutta) - NEVER 'tsu'.
- Topic particle 'は' -> 'wa'.
- Common pronoun readings (君 -> きみ, 僕 -> ぼく).
- Inflectional endings (た, て, ない) stay attached without erroneous word spaces.
"""

import pykakasi

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

_OVERRIDES = {"君": "きみ", "僕": "ぼく"}

_ATTACHED_SUFFIXES = {"た", "て", "だ", "で", "ない", "ます", "たって", "てる", "たい"}

_GLOBAL_KAKASI = None


def get_kakasi() -> pykakasi.kakasi:
    global _GLOBAL_KAKASI
    if _GLOBAL_KAKASI is None:
        _GLOBAL_KAKASI = pykakasi.kakasi()
    return _GLOBAL_KAKASI


def convert_tokens_to_morae(conv_tokens: list[dict]) -> list[dict]:
    """
    Given pykakasi conv tokens, convert them into individual morae with accurate Hepburn romaji.
    - Sokuon (っ / ッ) is converted to geminated consonant of succeeding mora (never 'tsu').
    - Particle 'は' is converted to 'wa'.
    - Tokens ending in sokuon (e.g. 眠っ + た) do not insert a space between stem and inflection.
    """
    # Pre-pass: mend cases where pykakasi splits kanji before a small kana (e.g. 来ち + ゃった)
    for i in range(len(conv_tokens) - 1):
        h2 = conv_tokens[i + 1].get("hira", "")
        if h2 and h2[0] in _SMALL_KANA:
            h1 = conv_tokens[i].get("hira", "")
            if h1:
                conv_tokens[i]["hira"] = h1[:-1]
                conv_tokens[i + 1]["hira"] = h1[-1] + h2
                o1 = conv_tokens[i].get("orig", "")
                if o1.endswith(h1[-1]):
                    conv_tokens[i]["orig"] = o1[:-1]
                    conv_tokens[i + 1]["orig"] = h1[-1] + conv_tokens[i + 1].get("orig", "")

    raw_morae: list[dict] = []
    for t_idx, t in enumerate(conv_tokens):
        orig = t.get("orig", "").strip()
        hira = t.get("hira", "").strip()
        if not orig:
            continue

        if orig in _OVERRIDES:
            hira = _OVERRIDES[orig]

        # ASCII / Latin words: split by whitespace so each word highlights as a unit
        if all(ord(c) < 128 for c in orig):
            words = orig.split()
            for w in words:
                clean_w = w.strip(".,!?\"'()[]{}~…")
                if clean_w:
                    raw_morae.append({
                        "orig": clean_w,
                        "mora": clean_w,
                        "rom": clean_w,
                        "token_idx": t_idx,
                        "is_token_end": True,
                        "is_sokuon": False,
                    })
            continue

        chars = [c for c in hira if not c.isspace() and c not in "、。・！？…〜~\"'()[]{}"]
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
            is_wa = False
            if m == "は":
                if orig in ("は", "ハ"):
                    is_wa = True
                elif is_end and (orig.endswith("は") or orig.endswith("ハ")):
                    is_wa = True

            # If token ends in sokuon, it attaches to the next token without a space
            if is_end and is_sokuon:
                is_end = False

            raw_morae.append({
                "orig": orig,
                "mora": m,
                "rom": "wa" if is_wa else (None if is_sokuon else _KANA_MORA_MAP.get(m, m)),
                "token_idx": t_idx,
                "is_token_end": is_end,
                "is_sokuon": is_sokuon,
            })

    # Pass 2: attach grammatical suffixes (た / て / ない) to preceding stem without space
    for idx in range(len(raw_morae) - 1):
        curr = raw_morae[idx]
        nxt = raw_morae[idx + 1]
        if curr["is_token_end"] and curr["token_idx"] != nxt["token_idx"]:
            nxt_orig = nxt["orig"]
            if nxt_orig in _ATTACHED_SUFFIXES:
                curr["is_token_end"] = False

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

    return raw_morae


def get_morae_for_text(text: str, k: pykakasi.kakasi | None = None) -> list[dict]:
    """Tokenize and return list of morae with accurate romaji and word boundary markers."""
    if k is None:
        k = get_kakasi()
    conv = k.convert(text)
    return convert_tokens_to_morae(conv)
