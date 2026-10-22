"""MusicXML <-> MIDI <-> numbered-notation (jianpu) core conversion.

Jianpu output is JSON Lines: each part starts with a ``type=part`` header and
one ``type=event`` row represents each source event. Event rows include part,
measure number, staff, voice, measure-local Fraction onset, positive duration,
kind, Jianpu pitch token(s), per-pitch tie states, lossless JSON lyrics, and a
grace flag. A chord remains one row with parallel pitch/tie arrays; rests use
pitch token ``0``. Grace events use duration ``1`` as a display sentinel and
``grace=true`` means they occupy no musical time. Fractions are rendered as
integers or ``numerator/denominator`` strings.

MusicXML is parsed to a ScoreModel once for conversion. Semantic validation is
blocking for both text and MIDI output.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from math import lcm
from pathlib import Path
from typing import Optional

import music21
import pretty_midi

from .jianpu import map_pitch
from .musicxml_io import load_musicxml
from .validation import validate_score


@dataclass
class ConvertOptions:
    """Common conversion options."""

    bpm: int = 90
    title: Optional[str] = None
    composer: Optional[str] = None


# ---------- MusicXML <-> MIDI ----------

def _validated_model(xml_path: str | Path):
    model = load_musicxml(xml_path)
    issues = validate_score(model)
    if issues:
        codes = ", ".join(dict.fromkeys(issue.code for issue in issues))
        raise ValueError(f"score validation failed: {codes}")
    return model


def _midi_pitch(pitch) -> int:
    natural = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return (pitch.octave + 1) * 12 + natural[pitch.step] + pitch.alter


def _seconds(beats: Fraction, bpm: float) -> float:
    return float(beats * 60 / Fraction(str(bpm)))


def musicxml_to_midi(xml_path: str | Path, midi_path: str | Path,
                     options: ConvertOptions | None = None) -> Path:
    """Convert validated ScoreModel events to MIDI, retaining parts and voices."""
    options = options or ConvertOptions()
    model = _validated_model(xml_path)
    bpm = model.tempo_bpm or options.bpm
    if bpm <= 0:
        raise ValueError("tempo must be positive")

    measure_starts: dict[int, Fraction] = {}
    cursor = Fraction(0)
    for measure in sorted(model.measures, key=lambda item: item.index):
        measure_starts[measure.index] = cursor
        cursor += measure.duration

    resolution = 480
    for part in model.parts:
        for event in part.events:
            absolute_onset = measure_starts[event.measure_index] + event.onset
            absolute_end = absolute_onset + event.duration
            resolution = lcm(resolution, absolute_onset.denominator, absolute_end.denominator)
    resolution = min(resolution, 32760)
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(bpm), resolution=resolution)
    for part in model.parts:
        voices: dict[tuple[str, str], list[tuple[Fraction, object]]] = {}
        for event in part.events:
            stream_key = (event.staff_number, event.voice_id)
            absolute_onset = measure_starts[event.measure_index] + event.onset
            voices.setdefault(stream_key, []).append((absolute_onset, event))

        for (staff_number, voice_id), events in sorted(voices.items()):
            instrument_name = f"{part.name} staff {staff_number} voice {voice_id}"
            track = pretty_midi.Instrument(program=0, name=instrument_name)
            pending_ties: dict[int, list[Fraction]] = {}
            for absolute_onset, event in sorted(
                events, key=lambda entry: (entry[0], entry[1].onset)
            ):
                if event.kind == "rest" or event.grace:
                    continue
                absolute_end = absolute_onset + event.duration
                sounding = event.effective_sounding_pitches
                states = event.pitch_ties or ("none",) * len(sounding)
                for index, pitch in enumerate(sounding):
                    midi_pitch = _midi_pitch(pitch)
                    state = states[index] if index < len(states) else "none"
                    if state == "start":
                        pending_ties.setdefault(midi_pitch, []).append(absolute_onset)
                    elif state == "stop":
                        starts = pending_ties.get(midi_pitch, [])
                        if starts:
                            tie_start = starts.pop(0)
                            track.notes.append(pretty_midi.Note(
                                velocity=80,
                                pitch=midi_pitch,
                                start=_seconds(tie_start, bpm),
                                end=_seconds(absolute_end, bpm),
                            ))
                            if not starts:
                                pending_ties.pop(midi_pitch, None)
                    elif state == "continue":
                        # The pending start remains open through tie continuations.
                        continue
                    else:
                        track.notes.append(pretty_midi.Note(
                            velocity=80,
                            pitch=midi_pitch,
                            start=_seconds(absolute_onset, bpm),
                            end=_seconds(absolute_end, bpm),
                        ))
            pm.instruments.append(track)

    midi_path = Path(midi_path)
    midi_path.parent.mkdir(parents=True, exist_ok=True)
    pm.write(str(midi_path))
    return midi_path


def midi_to_musicxml(midi_path: str | Path, xml_path: str | Path,
                     options: ConvertOptions | None = None) -> Path:
    """Convert a MIDI file to a MusicXML file.

    music21's MIDI parser reconstructs a best-effort part/measure structure.
    """
    midi_path = Path(midi_path)
    xml_path = Path(xml_path)
    xml_path.parent.mkdir(parents=True, exist_ok=True)

    score = music21.converter.parse(str(midi_path))
    score.write("musicxml", fp=str(xml_path))
    return xml_path


# ---------- Numbered notation (jianpu) ----------

_MAJOR_TONICS = {
    -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb",
    -1: "F", 0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B",
    6: "F#", 7: "C#",
}
_MINOR_TONICS = {
    -7: "Ab", -6: "Eb", -5: "Bb", -4: "F", -3: "C", -2: "G",
    -1: "D", 0: "A", 1: "E", 2: "B", 3: "F#", 4: "C#",
    5: "G#", 6: "D#", 7: "A#",
}


def _notation_key(model, tonic: str | None) -> tuple[str, str]:
    first_key = next(
        (
            measure
            for measure in sorted(model.measures, key=lambda item: item.index)
            if measure.fifths is not None and measure.mode in ("major", "minor")
        ),
        None,
    )
    if first_key is None:
        code = "missing_tonic" if tonic is None else "missing_key_mode"
        raise ValueError(f"{code}: movable notation requires a clear key context")
    key_mode = first_key.mode
    if tonic is not None:
        return tonic, key_mode
    table = _MAJOR_TONICS if key_mode == "major" else _MINOR_TONICS
    resolved_tonic = table.get(first_key.fifths)
    if resolved_tonic is None:
        raise ValueError("missing_tonic: unsupported key signature")
    return resolved_tonic, key_mode


def _pitch_token(pitch, *, mode: str, tonic: str | None, key_mode: str | None) -> str:
    degree, octave = map_pitch(
        pitch,
        tonic=tonic,
        key_mode=key_mode,
        notation=mode,
    )
    octave_suffix = f"^{octave}" if octave > 0 else f"v{-octave}" if octave < 0 else ""
    return f"{degree}{octave_suffix}"


def _fraction_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def musicxml_to_jianpu_text(
    xml_path: str | Path, *, mode: str = "movable", tonic: str | None = None
) -> str:
    """Return an auditable JSONL row for each part header and source event.

    Event keys are ``part``, ``measure``, ``staff``, ``voice``, local ``onset``,
    positive ``duration``, ``kind``, ``pitches``, per-pitch ``ties``, structured
    ``lyrics``, and ``grace``. Pitch and tie arrays stay parallel for chords;
    lyric strings are JSON-escaped without loss. Grace duration ``1`` is only a
    display sentinel; consumers must treat ``grace=true`` as zero-time.
    Movable notation anchors to the score's first explicit key context. A later
    key-signature-only change does not by itself imply a new tonic/modulation.
    """
    if mode not in ("movable", "fixed"):
        raise ValueError("mode must be 'movable' or 'fixed'")
    model = _validated_model(xml_path)
    resolved_tonic: str | None = None
    key_mode: str | None = None
    if mode == "movable":
        resolved_tonic, key_mode = _notation_key(model, tonic)

    measure_numbers = {measure.index: measure.number for measure in model.measures}
    lines: list[str] = []
    for part in model.parts:
        lines.append(json.dumps(
            {"type": "part", "part": part.id, "name": part.name},
            ensure_ascii=False,
            separators=(",", ":"),
        ))
        ordered_events = sorted(
            part.events,
            key=lambda item: (item.measure_index, item.onset, item.staff_number, item.voice_id),
        )
        for event in ordered_events:
            if event.kind == "rest":
                pitch_tokens: str | list[str] = "0"
                tie_states: list[str] = []
            else:
                pitch_tokens_list = [
                    _pitch_token(
                        pitch,
                        mode=mode,
                        tonic=resolved_tonic,
                        key_mode=key_mode,
                    )
                    for pitch in event.pitches
                ]
                pitch_tokens = (
                    pitch_tokens_list if event.kind == "chord" else pitch_tokens_list[0]
                )
                tie_states = list(event.pitch_ties or ("none",) * len(pitch_tokens_list))
            lyric_values = [
                {
                    "text": lyric.text,
                    "number": lyric.number,
                    "syllabic": lyric.syllabic,
                    "extend": lyric.extend,
                }
                for lyric in event.lyrics
            ]
            lines.append(json.dumps(
                {
                    "type": "event",
                    "part": event.part_id,
                    "measure": measure_numbers.get(event.measure_index, str(event.measure_index)),
                    "staff": event.staff_number,
                    "voice": event.voice_id,
                    "onset": _fraction_text(event.onset),
                    "duration": "1" if event.grace else _fraction_text(event.duration),
                    "kind": event.kind,
                    "pitches": pitch_tokens,
                    "ties": tie_states,
                    "lyrics": lyric_values,
                    "grace": event.grace,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ))
    return "\n".join(lines)


def jianpu_text_to_midi(jianpu: str, midi_path: str | Path,
                        options: ConvertOptions | None = None) -> Path:
    """Minimal jianpu-text -> MIDI converter.

    Accepted jianpu tokens:
        1 2 3 4 5 6 7   ->  C D E F G A B (starting from middle C)
        # / b           ->  sharp / flat prefix
        |               ->  bar separator (ignored; kept for readability)
        whitespace      ->  token separator

    Missing durations default to one quarter-note beat; tempo is taken from
    ``options.bpm``.
    """
    options = options or ConvertOptions()
    midi_path = Path(midi_path)
    midi_path.parent.mkdir(parents=True, exist_ok=True)

    pm = pretty_midi.PrettyMIDI(initial_tempo=options.bpm)
    inst = pretty_midi.Instrument(program=0)  # Acoustic Grand Piano
    time = 0.0
    beat = 60.0 / options.bpm  # one beat (seconds)
    token = ""
    for ch in jianpu:
        if ch in " \n\t|":
            _emit(token, time, beat, inst)
            time += beat
            token = ""
        else:
            token += ch
    _emit(token, time, beat, inst)
    if token:
        time += beat

    pm.instruments.append(inst)
    pm.write(str(midi_path))
    return midi_path


def jianpu_text_to_musicxml(jianpu: str, xml_path: str | Path,
                            options: ConvertOptions | None = None) -> Path:
    """jianpu text -> MusicXML: jianpu -> MIDI -> MusicXML."""
    options = options or ConvertOptions()
    tmp_midi = Path(xml_path).with_suffix(".tmp.mid")
    jianpu_text_to_midi(jianpu, tmp_midi, options)
    try:
        return midi_to_musicxml(tmp_midi, xml_path, options)
    finally:
        if tmp_midi.exists():
            tmp_midi.unlink()


# ---------- Internal helpers ----------

_PITCH_INDEX = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}


def _pitch_to_jianpu(p: music21.pitch.Pitch) -> str:
    """Convert a single pitch to its jianpu numeral.

    Jianpu octaves differ from staff notation: middle C is ``1`` and each
    ascending octave adds ``+`` to the numeral.
    """
    semitone = p.midi  # 60 = C4
    # C4 -> 1, D4 -> 2, ... B4 -> 7, C5 -> 1 (next octave)
    degree = (semitone - 60) % 12
    degree_to_num = {0: 1, 2: 2, 4: 3, 5: 4, 7: 5, 9: 6, 11: 7}
    accidental = ""
    if degree in (1, 3, 6, 8, 10):  # black key
        # In jianpu, a sharp on a white-key slot is written as 1#/2#/4#/5#/6#.
        white_key_offset = {1: 0, 3: 1, 6: 3, 8: 4, 10: 5}
        base_semitone = semitone - 1
        accidental = "#"
        if semitone % 12 == 1:  # C#/Db -> prefer the Db spelling
            base_semitone = semitone + 1
            accidental = "b"
    else:
        base_semitone = semitone
    octave = (base_semitone - 60) // 12
    base_semitone_in_octave = (base_semitone - 60) % 12
    num = degree_to_num[base_semitone_in_octave]
    # Higher/lower octaves: dots above/below. music21 uses ``+``/``-`` here
    # as a compact notation.
    suffix = ""
    if octave > 0:
        suffix = "+" * octave
    elif octave < 0:
        suffix = "-" * (-octave)
    return f"{accidental}{num}{suffix}"


def _emit(token: str, time: float, beat: float, inst: pretty_midi.Instrument) -> None:
    """Parse a single jianpu token and append a note."""
    if not token:
        return
    accidental = ""
    num_part = token
    if token and token[0] in "#b":
        accidental = token[0]
        num_part = token[1:]
    if not num_part or not num_part[0].isdigit():
        return
    digits = ""
    suffix = ""
    for c in num_part:
        if c.isdigit():
            digits += c
        else:
            suffix += c
    if not digits:
        return
    octave_offset = 0
    if "+" in suffix:
        octave_offset = suffix.count("+")
    if "-" in suffix:
        octave_offset = -suffix.count("-")
    # numeral -> semitone offset within an octave
    num_to_degree = {"1": 0, "2": 2, "3": 4, "4": 5, "5": 7, "6": 9, "7": 11}
    semitone = 60 + octave_offset * 12 + num_to_degree[digits[0]]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1
    note = pretty_midi.Note(velocity=80, pitch=semitone, start=time, end=time + beat)
    inst.notes.append(note)
