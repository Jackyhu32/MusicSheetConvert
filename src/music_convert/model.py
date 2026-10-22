from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal


@dataclass(frozen=True)
class Pitch:
    step: str
    alter: int
    octave: int


@dataclass(frozen=True)
class Lyric:
    text: str
    number: str = "1"
    syllabic: str = "single"
    extend: bool = False


@dataclass(frozen=True)
class SourceLocation:
    page: int | None = None
    system: int | None = None
    measure_number: str | None = None


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    message: str
    location: SourceLocation | None = None
    candidates: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True)
class StaffContext:
    number: str
    clef_sign: str | None = None
    clef_line: int | None = None
    clef_octave_change: int = 0


@dataclass(frozen=True)
class ScoreDirection:
    measure_index: int
    onset: Fraction
    kind: str
    value: str
    part_id: str | None = None
    staff_number: str | None = None


@dataclass(frozen=True)
class ScoreEvent:
    part_id: str
    measure_index: int
    voice_id: str
    onset: Fraction
    duration: Fraction
    kind: Literal["note", "rest", "chord"]
    pitches: tuple[Pitch, ...] = ()
    sounding_pitches: tuple[Pitch, ...] = ()
    pitch_ties: tuple[Literal["none", "start", "stop", "continue"], ...] = ()
    staff_number: str = "1"
    lyrics: tuple[Lyric, ...] = ()
    source_location: SourceLocation | None = None

    @property
    def written_pitches(self) -> tuple[Pitch, ...]:
        """Return pitches as notated, preserving the legacy ``pitches`` field."""
        return self.pitches

    @property
    def effective_sounding_pitches(self) -> tuple[Pitch, ...]:
        """Return explicit sounding pitches, rejecting unresolved pitched events."""
        if self.kind == "rest":
            return ()
        if not self.sounding_pitches:
            raise ValueError(
                "sounding pitches must be explicitly provided before conversion"
            )
        return self.sounding_pitches


@dataclass(frozen=True)
class MeasureContext:
    index: int
    number: str
    duration: Fraction
    fifths: int | None
    mode: str | None
    beats: int | None
    beat_type: int | None
    pickup: bool = False


@dataclass
class ScorePart:
    id: str
    name: str
    transpose_semitones: int = 0
    staves: list[StaffContext] = field(default_factory=list)
    events: list[ScoreEvent] = field(default_factory=list)


@dataclass
class ScoreModel:
    title: str
    parts: list[ScorePart]
    measures: list[MeasureContext]
    tempo_bpm: float | None = None
    directions: list[ScoreDirection] = field(default_factory=list)
    source_musicxml: bytes | None = None
    requires_review: bool = False
    review_issues: list[ReviewIssue] = field(default_factory=list)
