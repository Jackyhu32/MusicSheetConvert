# Score Model and Conversion Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flattened, fixed-C conversion with an event model that preserves source pitch, sounding pitch, exact timing, parts, lyrics, ties, and key state.

**Architecture:** Parse MusicXML into typed `ScoreModel` events with rational beat positions. Derive jianpu and MIDI from those events, retain the original MusicXML transcription as the editable staff-score output, and run semantic validators before export.

**Tech Stack:** Python 3.10+, `music21`, `pretty_midi`, `fractions.Fraction`, `unittest`.

---

## Execution Order

Run this plan first. The PDF renderer and CLI integration plans consume the model and conversion APIs introduced here. Use an isolated virtual environment because `music21` is not installed in the current sandbox.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Task 1: Define Typed Score Events

**Files:**
- Create: `src/music_convert/model.py`
- Create: `tests/test_score_model.py`

- [ ] **Step 1: Write the failing model test**

```python
from fractions import Fraction
import unittest

from src.music_convert.model import Lyric, Pitch, ScoreEvent, ScorePart, ScoreModel


class ScoreModelTests(unittest.TestCase):
    def test_event_keeps_exact_timing_pitch_and_lyric(self):
        event = ScoreEvent(
            part_id="S",
            measure_index=0,
            voice_id="1",
            onset=Fraction(1, 2),
            duration=Fraction(3, 2),
            kind="note",
            pitches=(Pitch("F", 1, 4),),
            lyrics=(Lyric("星", number="1"),),
        )
        self.assertEqual(Fraction(1, 2), event.onset)
        self.assertEqual(Pitch("F", 1, 4), event.pitches[0])
        self.assertEqual("星", event.lyrics[0].text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm the missing-model failure**

Run: `python -m unittest discover -s tests -p test_score_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.music_convert.model'`.

- [ ] **Step 3: Add the model types**

Implement the exact constructors used by the test and add `MeasureContext` and `ScoreModel`:

```python
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
    # One tie state per pitch; chord ties need not apply to every tone.
    pitch_ties: tuple[Literal["none", "start", "stop", "continue"], ...] = ()
    staff_number: str = "1"
    lyrics: tuple[Lyric, ...] = ()
    source_location: SourceLocation | None = None


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
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python -m unittest discover -s tests -p test_score_model.py -v`
Expected: `OK`.

- [ ] **Step 5: Commit the model**

```bash
git add src/music_convert/model.py tests/test_score_model.py
git commit -m "feat: add typed score event model"
```

## Task 2: Parse MusicXML Without Flattening

**Files:**
- Create: `src/music_convert/musicxml_io.py`
- Create: `tests/fixtures/satbb-two-measures.musicxml`
- Create: `tests/fixtures/g-major-two-bars.musicxml`
- Modify: `tests/test_score_model.py`

- [ ] **Step 1: Add a failing MusicXML import test**

Create `satbb-two-measures.musicxml` with five uniquely named SATBB parts, two 4/4 measures, a dotted duration, a rest, a chord, a Chinese lyric, a cross-measure tie, and an explicit key/time change. Create `g-major-two-bars.musicxml` with one Soprano part in G major, two 4/4 measures, and a known sequence beginning G4-A4-B4-C5. Assert all SATBB part names and event positions survive parsing:

```python
import unittest
from pathlib import Path

from src.music_convert.musicxml_io import load_musicxml


FIXTURE = Path(__file__).parent / "fixtures" / "satbb-two-measures.musicxml"


class MusicXmlParsingTests(unittest.TestCase):
    def test_import_preserves_parts_events_and_lyrics(self):
        model = load_musicxml(FIXTURE)
        self.assertEqual(
            ["Soprano", "Alto", "Tenor", "Baritone", "Bass"],
            [part.name for part in model.parts],
        )
        soprano = model.parts[0].events
        self.assertTrue(any(event.kind == "rest" for event in soprano))
        self.assertTrue(any("start" in event.pitch_ties for event in soprano))
        self.assertTrue(any(
            lyric.text == "星" for event in soprano for lyric in event.lyrics
        ))
        self.assertEqual(4, model.measures[0].beats)
        self.assertEqual("major", model.measures[0].mode)
        self.assertEqual(1, len(model.parts[0].events[0].pitches))
```

- [ ] **Step 2: Run and confirm the parser failure**

Run: `python -m unittest discover -s tests -p test_score_model.py -v`
Expected: FAIL because `load_musicxml` is not defined.

- [ ] **Step 3: Implement MusicXML parsing**

Implement `load_musicxml(path: str | Path) -> ScoreModel` and `score_to_model(score: music21.stream.Score, source_musicxml: bytes | None = None) -> ScoreModel` in `musicxml_io.py`. For each part, iterate measures, then each `Voice` (or the measure itself when there is no `Voice`), then `notesAndRests`; obtain exact quarter lengths from music21's rational duration value when available, converting to `Fraction` without passing through a rounded float. A `Chord` is one event containing every pitch, with a parallel per-pitch tie state. Preserve staff/clef context, written pitch, concert/sounding pitch, tie type (`none`, `start`, `stop`, or `continue`), lyric number/syllabic/extend, key and meter at every change, instrument transposition, title, tempo, supported dynamics/directions, and original MusicXML bytes. Do not infer modulation from key-signature changes alone. Keep source locations and `ReviewIssue` candidates when supplied by OMR or visual transcription. Do not use `score.recurse().notes` as the event source because it loses part, rest, measure, and voice boundaries.

- [ ] **Step 4: Run the parser test**

Run: `python -m unittest discover -s tests -p test_score_model.py -v`
Expected: `OK`; all five source parts and tested events are present.

- [ ] **Step 5: Commit the parser**

```bash
git add src/music_convert/musicxml_io.py tests/fixtures/satbb-two-measures.musicxml tests/fixtures/g-major-two-bars.musicxml tests/test_score_model.py
git commit -m "feat: parse musicxml into score events"
```

## Task 3: Add Movable-Do and Fixed-Do Mapping

**Files:**
- Create: `src/music_convert/jianpu.py`
- Create: `tests/test_jianpu.py`

- [ ] **Step 1: Write mapping tests**

```python
import unittest

from src.music_convert.jianpu import map_pitch
from src.music_convert.model import Pitch


class JianpuMappingTests(unittest.TestCase):
    def test_movable_major_maps_tonic_to_one(self):
        self.assertEqual(("1", 0), map_pitch(
            Pitch("G", 0, 4), tonic="G", key_mode="major", notation="movable"
        ))


    def test_movable_minor_maps_tonic_to_six(self):
        self.assertEqual(("6", 0), map_pitch(
            Pitch("A", 0, 4), tonic="A", key_mode="minor", notation="movable"
        ))


    def test_fixed_do_keeps_c_as_one_in_every_key(self):
        self.assertEqual(("1", 0), map_pitch(Pitch("C", 0, 4), notation="fixed"))
        self.assertEqual(("2", 0), map_pitch(Pitch("D", 0, 4), notation="fixed"))


    def test_chromatic_spelling_is_preserved_as_an_altered_degree(self):
        self.assertEqual(("#4", 0), map_pitch(
            Pitch("F", 1, 4), tonic="C", key_mode="major", notation="movable"
        ))
```

- [ ] **Step 2: Run and confirm the mapping import failure**

Run: `python -m unittest discover -s tests -p test_jianpu.py -v`
Expected: FAIL because `src.music_convert.jianpu` does not exist.

- [ ] **Step 3: Implement the mapping API**

Add `map_pitch(pitch, *, tonic=None, key_mode=None, notation="movable") -> tuple[str, int]`. `notation` selects movable or fixed do; `key_mode` selects major or minor and must not be confused with the notation mode. Use source spelling (`step`, `alter`) to determine diatonic degree, then apply chromatic alteration; do not infer enharmonic spellings from MIDI pitch class. Return the jianpu token and octave offset. For minor keys, interpret `tonic` as the minor tonic and use its relative-major degree frame so the tonic is `6`; for fixed mode, use `C=1`.

- [ ] **Step 4: Run mapping tests**

Run: `python -m unittest discover -s tests -p test_jianpu.py -v`
Expected: `OK`.

- [ ] **Step 5: Commit the mapper**

```bash
git add src/music_convert/jianpu.py tests/test_jianpu.py
git commit -m "feat: map score pitches to jianpu"
```

## Task 4: Validate Measure Timing and Ties

**Files:**
- Create: `src/music_convert/validation.py`
- Create: `tests/test_score_validation.py`

- [ ] **Step 1: Add failing timeline tests**

Add these cases to `tests/test_score_validation.py`:

```python
from fractions import Fraction
import unittest

from src.music_convert.model import MeasureContext, Pitch, ScoreEvent, ScoreModel, ScorePart
from src.music_convert.validation import validate_score


class ScoreValidationTests(unittest.TestCase):
    def model(self, events, *, pickup=False):
        measures = [MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)]
        if pickup:
            measures[0] = MeasureContext(
                0, "1", Fraction(1), 0, "major", 4, 4, pickup=True
            )
        return ScoreModel("", [ScorePart("S", "Soprano", events=events)], measures)

    def test_quarter_and_tuplet_fractions_cover_measure(self):
        events = [
            ScoreEvent("S", 0, "1", Fraction(0), Fraction(1), "note",
                       (Pitch("C", 0, 4),)),
            ScoreEvent("S", 0, "1", Fraction(1), Fraction(1, 3), "note",
                       (Pitch("D", 0, 4),)),
            ScoreEvent("S", 0, "1", Fraction(4, 3), Fraction(1, 3), "note",
                       (Pitch("E", 0, 4),)),
            ScoreEvent("S", 0, "1", Fraction(5, 3), Fraction(1, 3), "note",
                       (Pitch("F", 0, 4),)),
            ScoreEvent("S", 0, "1", Fraction(2), Fraction(2), "rest"),
        ]
        self.assertEqual([], validate_score(self.model(events)))

    def test_pickup_uses_declared_length(self):
        event = ScoreEvent("S", 0, "1", Fraction(0), Fraction(1), "note",
                           (Pitch("C", 0, 4),))
        self.assertEqual([], validate_score(self.model([event], pickup=True)))

    def test_tie_with_different_pitch_is_reported(self):
        events = [
            ScoreEvent("S", 0, "1", Fraction(0), Fraction(4), "note",
                       (Pitch("C", 0, 4),), pitch_ties=("start",)),
            ScoreEvent("S", 1, "1", Fraction(0), Fraction(1), "note",
                       (Pitch("D", 0, 4),), pitch_ties=("stop",)),
        ]
        model = self.model(events)
        model.measures.append(
            MeasureContext(1, "2", Fraction(4), 0, "major", 4, 4)
        )
        issues = validate_score(model)
        self.assertEqual("tie_pitch_mismatch", issues[0].code)
        self.assertEqual("S", issues[0].part_id)
        self.assertEqual("2", issues[0].measure_number)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm the missing-validator failure**

Run: `python -m unittest discover -s tests -p test_score_validation.py -v`
Expected: FAIL because `validate_score` is not defined.

- [ ] **Step 3: Implement deterministic validation**

Add `ValidationIssue(code: str, part_id: str, measure_number: str, message: str)` and `validate_score(model: ScoreModel) -> list[ValidationIssue]`. Group events by `(part_id, measure_index, voice_id)`, sort by onset, compare occupied intervals against `MeasureContext.duration`, and emit `measure_gap`, `measure_overlap`, or `measure_overflow`. Skip the full-meter equality check only when `pickup=True`; still reject events extending beyond the declared pickup length. For each pitch in a note or chord, keep pending ties by `(part_id, staff_number, voice_id, written pitch, sounding pitch)` and require a matching stop/continue at the next contiguous absolute onset, calculated from cumulative measure durations; report orphan stops, unmatched starts, pitch mismatches, and discontinuities. Chord tones share one event duration and are never summed independently. Preserve confidence and unresolved source candidates as `ReviewIssue` entries; validation must not silently resolve them.

- [ ] **Step 4: Run validator tests**

Run: `python -m unittest discover -s tests -p test_score_validation.py -v`
Expected: `OK`; invalid fixtures produce stable issue codes and valid exceptions produce no issue.

- [ ] **Step 5: Commit the validator**

```bash
git add src/music_convert/validation.py tests/test_score_validation.py
git commit -m "feat: validate score timing and ties"
```

## Task 5: Route Existing Converters Through the Model

**Files:**
- Modify: `src/music_convert/core.py`
- Modify: `src/music_convert/__init__.py`
- Modify: `tests/smoke.py`
- Create: `tests/test_conversion_core.py`

- [ ] **Step 1: Add failing conversion assertions**

Add the following contract test, then extend it with one rest, one lyric, one tie, and one SATBB fixture assertion:

```python
import unittest
from pathlib import Path

from src.music_convert.core import musicxml_to_jianpu_text


class ConversionCoreTests(unittest.TestCase):
    def test_movable_key_is_used_and_measure_boundary_is_kept(self):
        fixture = Path("tests/fixtures/g-major-two-bars.musicxml")
        text = musicxml_to_jianpu_text(fixture, mode="movable")
        self.assertIn("1", text)  # G4 is the tonic in movable-do.
        self.assertIn("|", text)
        self.assertIn("part=Soprano", text)

    def test_fixed_mode_uses_c_as_one(self):
        fixture = Path("tests/fixtures/g-major-two-bars.musicxml")
        text = musicxml_to_jianpu_text(fixture, mode="fixed")
        self.assertIn("1", text)
        self.assertIn("2", text)


if __name__ == "__main__":
    unittest.main()
```

Use this lossless text-token grammar so durations, octave, lyrics, and ties survive without overloading `-`:

```text
event := part-id TAB measure-number TAB onset TAB pitch-list TAB duration TAB lyric-list TAB tie
pitch-list := pitch | "[" pitch ("," pitch)* "]" | "0"
pitch := [ "#" | "b" ] degree [ "^" octave | "v" octave ]
duration := positive-integer [ "/" positive-integer ]
tie := "start" | "stop" | "continue" | "-"
```

`onset` and `duration` are rational quarter-note beats (for example `3/2`); `onset` is local to the measure and a `0` pitch list represents a rest. Emit one header line per part and one event line per source event. Resolve the active key context for each event from the measure timeline; do not infer a modulation solely from a changed key signature.

- [ ] **Step 2: Run the new tests**

Run: `python -m unittest discover -s tests -p test_conversion_core.py -v`
Expected: FAIL because `core.musicxml_to_jianpu_text` still flattens events and has no key/mode options.

- [ ] **Step 3: Replace the flattened implementation**

Keep existing public function names as wrappers. Make `musicxml_to_jianpu_text(path, *, mode="movable", tonic=None)` call `load_musicxml`, `validate_score`, and the event formatter; here `mode` means Jianpu notation mode (`movable` or `fixed`), while key major/minor comes from explicit score context. The formatter's output records each event once, with source part and measure identity. Update MusicXML-to-MIDI to derive absolute note starts from cumulative measure durations and derive note ends and pitches from model events' `sounding_pitches`. Reject invalid output states and preserve the original MusicXML source bytes for the editable staff-score artifact.

- [ ] **Step 4: Run core and legacy tests**

Run: `python -m unittest discover -s tests -v`
Expected: `OK`.

Run: `python tests/smoke.py`
Expected: `ALL TESTS PASSED`.

- [ ] **Step 5: Commit the conversion core**

```bash
git add src/music_convert/core.py src/music_convert/__init__.py tests/smoke.py tests/test_conversion_core.py
git commit -m "feat: preserve score events in conversions"
```

## Completion Check

- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run `python tests/smoke.py`, `python tests/e2e_cli.py`, and `python tests/complex_e2e.py`.
- [ ] Confirm fixtures cover major, minor (`tonic=6`), fixed `C=1`, altered pitches, ties, rests, tuplets, lyrics, chords, and five parts.
- [ ] Do not report the uploaded scanned score as a ground-truth accuracy pass until an original MusicXML file or user-verified excerpt is available.
