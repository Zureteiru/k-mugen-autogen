from dataclasses import dataclass, field


@dataclass
class MoraTiming:
    hiragana: str
    romaji: str
    start_sec: float
    end_sec: float
    pre_gap_cs: int = 0

    @property
    def duration_cs(self) -> int:
        return max(1, int(round((self.end_sec - self.start_sec) * 100)))


@dataclass
class LyricLine:
    original_text: str
    start_sec: float
    end_sec: float
    morae: list[MoraTiming]
    translation: str | None = None


@dataclass
class SongBundle:
    title: str
    artist: str
    video_path: str
    audio_path: str
    vocal_stem_path: str | None = None
    inst_stem_path: str | None = None
    lines: list[LyricLine] = field(default_factory=list)
