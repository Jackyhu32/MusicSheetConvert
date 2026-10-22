"""Advanced score builders: grand staff (two hands), multiple key signatures, chord progressions, complex rhythms.

Builds ``music21`` Streams directly and emits MusicXML / MIDI without any
external OMR. Importable via:
    ``from src.music_convert.advanced import build_demo_score``
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import music21
from music21 import chord, key, meter, note, pitch, stream

# Key-signature presets expressed with music21 ``key.Key`` objects.
KEY_PRESETS = {
    "C": key.Key("C"),
    "G": key.Key("G"),
    "D": key.Key("D"),
    "F": key.Key("F"),
    "Bb": key.Key("B-"),
    "Eb": key.Key("E-"),
    "Am": key.Key("a"),
    "Em": key.Key("e"),
    "Dm": key.Key("d"),
}


@dataclass
class NoteSpec:
    """Description of a single note (or a chord). Supports pitch list / duration / velocity / tie."""

    pitches: Sequence[str]  # e.g. ["C4", "E4", "G4"] or ["C4"]
    quarter_length: float = 1.0
    velocity: int = 80
    tie: str | None = None  # "start" / "stop" / None


@dataclass
class HandPart:
    """A single hand / part (e.g. right hand, left hand, piano)."""

    name: str
    clef: str = "treble"  # "treble" / "bass" / "alto"
    instrument_program: int = 0  # MIDI program number
    measures: list[list[NoteSpec]] = field(default_factory=list)


# ---------------- Builders ----------------


def build_grand_staff(
    right_hand_measures: Sequence[Sequence[NoteSpec]],
    left_hand_measures: Sequence[Sequence[NoteSpec]],
    *,
    key_name: str = "C",
    time_sig: str = "4/4",
    title: str = "Grand Staff Demo",
    composer: str = "MusicSheetConvert",
) -> music21.stream.Score:
    """Build a two-part (piano) Score.

    Args:
        right_hand_measures: 2-D list, outer = measures, inner = notes within the measure.
        left_hand_measures:  Same shape as ``right_hand_measures``.
    """
    k = KEY_PRESETS.get(key_name, key.Key("C"))
    ts = meter.TimeSignature(time_sig)

    score = stream.Score()
    score.metadata = music21.metadata.Metadata(title=title, composer=composer)

    # ---- Right hand: upper part (Part 0) ----
    rh_part = stream.Part()
    rh_part.partName = "Piano RH"
    rh_part.insert(0, instrument_safe_program(0))
    rh_part.insert(0, k)
    rh_part.insert(0, ts)
    for measure_specs in right_hand_measures:
        m = stream.Measure()
        for spec in measure_specs:
            m.append(_build_note_or_chord(spec))
        rh_part.append(m)
    score.insert(0, rh_part)

    # ---- Left hand: lower part (Part 1) ----
    lh_part = stream.Part()
    lh_part.partName = "Piano LH"
    lh_part.insert(0, instrument_safe_program(0))  # Acoustic Grand Piano
    lh_part.insert(0, k)
    lh_part.insert(0, ts)
    for measure_specs in left_hand_measures:
        m = stream.Measure()
        for spec in measure_specs:
            m.append(_build_note_or_chord(spec))
        lh_part.append(m)
    score.insert(0, lh_part)
    return score


def build_chord_progression(
    chords: Sequence[Sequence[str]],
    *,
    key_name: str = "C",
    quarter_per_chord: float = 2.0,
    title: str = "Chord Progression",
) -> music21.stream.Score:
    """Build a simple chord progression. Useful for demonstrating key signature + chord rendering."""
    k = KEY_PRESETS.get(key_name, key.Key("C"))
    score = stream.Score()
    score.metadata = music21.metadata.Metadata(title=title)
    part = stream.Part()
    part.insert(0, instrument_safe_program(0))
    part.insert(0, k)
    part.insert(0, meter.TimeSignature("4/4"))
    for chord_pitches in chords:
        m = stream.Measure()
        c = chord.Chord([pitch.Pitch(p) for p in chord_pitches])
        c.quarterLength = quarter_per_chord
        m.append(c)
        part.append(m)
    score.insert(0, part)
    return score


def build_key_demonstration() -> music21.stream.Score:
    """Build a short passage covering every key signature in ``KEY_PRESETS``.

    Each key gets one measure containing a I (tonic triad) and a V7
    (dominant seventh) chord, in 4/4 time.
    """
    score = stream.Score()
    score.metadata = music21.metadata.Metadata(title="Key Signatures Demo")
    part = stream.Part()
    part.insert(0, instrument_safe_program(0))
    part.append(meter.TimeSignature("4/4"))

    for k in KEY_PRESETS.values():
        # Switch key signature for the new measure.
        m = stream.Measure()
        m.append(k)
        # I chord: build a major triad on the tonic.
        tonic = pitch.Pitch(k.tonic.nameWithOctave)
        third = tonic.transpose(4)  # major third
        fifth = tonic.transpose(7)  # perfect fifth
        c1 = chord.Chord([tonic, third, fifth])
        c1.quarterLength = 2.0
        m.append(c1)
        # V7 chord: tonic + 7th up.
        dom = tonic.transpose(7)
        dom7 = tonic.transpose(10)
        dom9 = tonic.transpose(14)
        dom11 = tonic.transpose(17)
        c2 = chord.Chord([dom, dom7, dom9, dom11])
        c2.quarterLength = 2.0
        m.append(c2)
        part.append(m)
    score.insert(0, part)
    return score


# ---------------- Preset classical pieces ----------------

# Bach Prelude in C major (BWV 846), first 4 measures - the classic broken-chord pattern.
BACH_PRELUDE_C_MAJOR_M1_M4 = [
    # Right hand: 8-note broken-chord pattern
    [
        NoteSpec(["C5"], 0.5),
        NoteSpec(["E5"], 0.5),
        NoteSpec(["G5"], 0.5),
        NoteSpec(["C6"], 0.5),
        NoteSpec(["E5"], 0.5),
        NoteSpec(["G5"], 0.5),
        NoteSpec(["C6"], 0.5),
        NoteSpec(["E6"], 0.5),
    ],
    [
        NoteSpec(["C5"], 0.5),
        NoteSpec(["D5"], 0.5),
        NoteSpec(["A5"], 0.5),
        NoteSpec(["D5"], 0.5),
        NoteSpec(["C5"], 0.5),
        NoteSpec(["D5"], 0.5),
        NoteSpec(["A5"], 0.5),
        NoteSpec(["D5"], 0.5),
    ],
    [
        NoteSpec(["B4"], 0.5),
        NoteSpec(["D5"], 0.5),
        NoteSpec(["G5"], 0.5),
        NoteSpec(["D5"], 0.5),
        NoteSpec(["B4"], 0.5),
        NoteSpec(["D5"], 0.5),
        NoteSpec(["G5"], 0.5),
        NoteSpec(["D5"], 0.5),
    ],
    [
        NoteSpec(["C5"], 0.5),
        NoteSpec(["E5"], 0.5),
        NoteSpec(["G5"], 0.5),
        NoteSpec(["C6"], 0.5),
        NoteSpec(["E5"], 0.5),
        NoteSpec(["G5"], 0.5),
        NoteSpec(["C6"], 0.5),
        NoteSpec(["E6"], 0.5),
    ],
]
BACH_PRELUDE_C_MAJOR_LH = [
    [NoteSpec(["C2", "G2", "C3", "E3"], 2.0), NoteSpec(["C2", "G2", "C3", "E3"], 2.0)],
    [NoteSpec(["A1", "E2", "A2", "C3"], 2.0), NoteSpec(["A1", "E2", "A2", "C3"], 2.0)],
    [NoteSpec(["G1", "D2", "G2", "B2"], 2.0), NoteSpec(["G1", "D2", "G2", "B2"], 2.0)],
    [NoteSpec(["C2", "G2", "C3", "E3"], 2.0), NoteSpec(["C2", "G2", "C3", "E3"], 2.0)],
]


def build_bach_prelude_c_major() -> music21.stream.Score:
    """Build the first 4 measures of Bach's Prelude in C major (BWV 846) for two hands."""
    return build_grand_staff(
        BACH_PRELUDE_C_MAJOR_M1_M4,
        BACH_PRELUDE_C_MAJOR_LH,
        key_name="C",
        title="Bach Prelude in C major (BWV 846) - m1..m4",
        composer="J.S. Bach",
    )


# ---------------- Writer ----------------


def write_score(
    score: music21.stream.Score, out_dir: str | Path, base_name: str = "score"
) -> dict[str, Path]:
    """Write a Score to MusicXML + MIDI. Returns a dict of output paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    xml_path = out_dir / f"{base_name}.musicxml"
    midi_path = out_dir / f"{base_name}.mid"
    score.write("musicxml", fp=str(xml_path))
    score.write("midi", fp=str(midi_path))
    return {"musicxml": xml_path, "midi": midi_path}


# ---------------- Internal helpers ----------------


def _build_note_or_chord(spec: NoteSpec) -> music21.note.GeneralNote:
    if len(spec.pitches) == 1:
        n = note.Note(spec.pitches[0])
    else:
        n = chord.Chord([pitch.Pitch(p) for p in spec.pitches])
    n.quarterLength = spec.quarter_length
    if hasattr(n, "volume") and n.volume is not None and spec.velocity:
        n.volume.velocity = spec.velocity
    if spec.tie == "start":
        n.tie = music21.tie.Tie("start")
    elif spec.tie == "stop":
        n.tie = music21.tie.Tie("stop")
    return n


def instrument_safe_program(program: int):
    """Return an ``Instrument`` instance with ``midiProgram`` set.

    music21 7.x and 9.x disagree on where ``Piano`` lives; this wrapper
    falls back to a generic ``Instrument`` if needed.
    """
    try:
        from music21 import instrument as inst_mod

        instr = inst_mod.Instrument()
        instr.midiProgram = program
        return instr
    except Exception:  # noqa: BLE001 - compatibility fallback across music21 versions
        return music21.instrument.Instrument()
