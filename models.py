from dataclasses import dataclass, field


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


@dataclass
class SongBundle:
    title: str
    artist: str
    video_path: str
    audio_path: str
    vocal_stem_path: str | None = None
    inst_stem_path: str | None = None
    lines: list[LyricLine] = field(default_factory=list)
