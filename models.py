from dataclasses import dataclass


@dataclass
class MoraTiming:
    hiragana: str
    romaji: str
    start_sec: float
    end_sec: float


@dataclass
class LyricLine:
    original_text: str
    start_sec: float
    end_sec: float
    morae: list[MoraTiming]
