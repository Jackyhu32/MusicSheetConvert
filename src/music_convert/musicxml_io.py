"""Import MusicXML scores into lossless, measure-oriented score events."""

from __future__ import annotations

import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any

from music21 import (
    chord,
    clef,
    converter,
    dynamics,
    expressions,
    instrument,
    key,
    meter,
    note,
    spanner,
    stream,
    tempo,
)
from music21.common.numberTools import opFrac

from .model import (
    Lyric,
    MeasureContext,
    Pitch,
    ReviewIssue,
    ScoreDirection,
    ScoreEvent,
    ScoreModel,
    ScorePart,
    SourceLocation,
    StaffContext,
)


def _fraction(value: Any) -> Fraction:
    """Convert music21 timing values without rounding their float representation."""
    value = opFrac(value)
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local_name(child) == name), None)


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local_name(child) == name]


def _text(element: ET.Element | None, default: str | None = None) -> str | None:
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _xml_root(source: bytes) -> ET.Element | None:
    """Read MusicXML from plain XML or the root member of an MXL archive."""
    try:
        if zipfile.is_zipfile(BytesIO(source)):
            with zipfile.ZipFile(BytesIO(source)) as archive:
                members = set(archive.namelist())
                container_name = "META-INF/container.xml"
                if container_name in members:
                    container = ET.fromstring(archive.read(container_name))
                    rootfile = next(
                        (
                            element
                            for element in container.iter()
                            if _local_name(element) == "rootfile"
                        ),
                        None,
                    )
                    root_path = (
                        rootfile.get("full-path") if rootfile is not None else None
                    )
                else:
                    root_path = None
                if root_path not in members:
                    root_path = next(
                        (
                            name
                            for name in archive.namelist()
                            if name.lower().endswith((".musicxml", ".xml"))
                            and not name.lower().startswith("meta-inf/")
                        ),
                        None,
                    )
                if root_path is None:
                    return None
                return ET.fromstring(archive.read(root_path))
        return ET.fromstring(source)
    except (ET.ParseError, OSError, zipfile.BadZipFile, KeyError):
        return None


def _xml_pitch(note_element: ET.Element) -> tuple[str, int, int] | None:
    pitch_element = _child(note_element, "pitch")
    if pitch_element is None:
        return None
    step = _text(_child(pitch_element, "step"))
    octave = _text(_child(pitch_element, "octave"))
    alter = _text(_child(pitch_element, "alter"), "0")
    if step is None or octave is None:
        return None
    alter_value = Fraction(alter or "0")
    if alter_value.denominator != 1:
        return None
    return step, alter_value.numerator, int(octave)


def _xml_lyrics(note_element: ET.Element) -> list[Lyric]:
    result: list[Lyric] = []
    for lyric_element in _children(note_element, "lyric"):
        text_value = _text(_child(lyric_element, "text"), "") or ""
        number = lyric_element.get("number") or lyric_element.get("name") or "1"
        syllabic = _text(_child(lyric_element, "syllabic"), "single") or "single"
        result.append(
            Lyric(
                text=text_value,
                number=str(number),
                syllabic=syllabic,
                extend=_child(lyric_element, "extend") is not None,
            )
        )
    return result


def _xml_tie(note_element: ET.Element) -> str:
    types = {
        element.get("type")
        for element in note_element.iter()
        if _local_name(element) in {"tie", "tied"} and element.get("type")
    }
    if "start" in types and "stop" in types:
        return "continue"
    if "start" in types:
        return "start"
    if "stop" in types:
        return "stop"
    return "none"


def _xml_slurs(note_element: ET.Element) -> list[tuple[str, str]]:
    marks = []
    for element in note_element.iter():
        if _local_name(element) != "slur":
            continue
        slur_type = element.get("type")
        if slur_type in {"start", "stop", "continue"}:
            marks.append((slur_type, str(element.get("number") or "1")))
    return marks


def _source_details(source: bytes | None) -> dict[str, Any] | None:
    """Supplement music21's stream with MusicXML-only ids and lyric extenders."""
    if source is None:
        return None
    root = _xml_root(source)
    if root is None:
        return None

    score_parts = [
        element for element in root.iter() if _local_name(element) == "score-part"
    ]
    names = {
        element.get("id", ""): _text(_child(element, "part-name"), "") or ""
        for element in score_parts
    }
    parts = _children(root, "part") if _local_name(root) == "score-partwise" else []
    details: dict[str, Any] = {
        "part_info": [],
        "events": {},
        "staves": {},
        "pickups": {},
        "clefs": {},
        "titles": [],
    }
    for element in root.iter():
        if _local_name(element) in {"work-title", "movement-title"} and element.text:
            details["titles"].append(element.text.strip())

    for part_index, part_element in enumerate(parts):
        part_id = part_element.get("id", str(part_index + 1))
        details["part_info"].append((part_id, names.get(part_id, "")))
        staff_contexts: dict[str, StaffContext] = {}
        divisions = 1
        for measure_index, measure_element in enumerate(
            _children(part_element, "measure")
        ):
            key = (part_index, measure_index)
            events: list[dict[str, Any]] = []
            details["events"][key] = events
            details["pickups"][key] = measure_element.get("implicit", "no").lower() in {
                "yes",
                "true",
                "1",
            }
            details["clefs"][key] = []
            cursor = Fraction(0)
            last_event: dict[str, Any] | None = None
            for element in measure_element:
                tag = _local_name(element)
                if tag == "attributes":
                    value = _text(_child(element, "divisions"))
                    if value:
                        divisions = int(value)
                    for clef_element in _children(element, "clef"):
                        staff_number = clef_element.get("number", "1")
                        sign = _text(_child(clef_element, "sign"))
                        line = _text(_child(clef_element, "line"))
                        octave = _text(_child(clef_element, "clef-octave-change"), "0")
                        clef_line = int(line) if line else None
                        octave_change = int(octave or 0)
                        staff_contexts.setdefault(
                            staff_number,
                            StaffContext(
                                number=staff_number,
                                clef_sign=sign,
                                clef_line=clef_line,
                                clef_octave_change=octave_change,
                            ),
                        )
                        details["clefs"][key].append(
                            (cursor, staff_number, sign, clef_line, octave_change)
                        )
                elif tag in {"backup", "forward"}:
                    amount = _text(_child(element, "duration"), "0") or "0"
                    delta = Fraction(int(amount), divisions)
                    cursor += delta if tag == "forward" else -delta
                    last_event = None
                elif tag == "note":
                    duration_text = _text(_child(element, "duration"), "0") or "0"
                    duration = Fraction(int(duration_text), divisions)
                    is_chord_tone = _child(element, "chord") is not None
                    if is_chord_tone and last_event is not None:
                        event = last_event
                    else:
                        voice = _text(_child(element, "voice"), "1") or "1"
                        staff = _text(_child(element, "staff"), "1") or "1"
                        event = {
                            "onset": cursor,
                            "voice": str(voice),
                            "staff": str(staff),
                            "pitches": [],
                            "ties": [],
                            "slurs": [],
                            "lyrics": [],
                            "duration": duration,
                        }
                        events.append(event)
                        last_event = event
                    pitch_value = _xml_pitch(element)
                    if pitch_value is not None:
                        event["pitches"].append(pitch_value)
                        event["ties"].append(_xml_tie(element))
                    event["slurs"].extend(_xml_slurs(element))
                    event["lyrics"].extend(_xml_lyrics(element))
                    if not is_chord_tone:
                        cursor += duration
                else:
                    last_event = None
            details["staves"][part_index] = staff_contexts
    return details


def _pitch_from_music21(value: Any) -> Pitch:
    accidental = value.accidental
    alter = Fraction(str(accidental.alter)) if accidental is not None else Fraction(0)
    if alter.denominator != 1:
        raise ValueError(f"MusicXML microtonal alteration is not supported: {alter}")
    return Pitch(str(value.step), alter.numerator, int(value.octave))


def _pitch_key(pitches: tuple[Pitch, ...]) -> tuple[tuple[str, int], ...]:
    return tuple((pitch.step, pitch.octave) for pitch in pitches)


def _match_source_event(
    source_events: list[dict[str, Any]],
    onset: Fraction,
    voice_id: str,
    pitches: tuple[Pitch, ...],
) -> dict[str, Any] | None:
    candidates = [event for event in source_events if event["onset"] == onset]
    voice_matches = [event for event in candidates if event["voice"] == voice_id]
    if voice_matches:
        candidates = voice_matches
    staff_matches = [
        event for event in candidates if len(event["pitches"]) == len(pitches)
    ]
    if staff_matches:
        candidates = staff_matches
    expected = _pitch_key(pitches)
    for index, event in enumerate(candidates):
        actual = tuple((item[0], item[2]) for item in event["pitches"])
        if actual == expected:
            source_events.remove(event)
            return event
    if candidates:
        selected = candidates[0]
        source_events.remove(selected)
        return selected
    return None


def _music21_ties(value: Any) -> tuple[str, ...]:
    if isinstance(value, chord.Chord):
        notes = value.notes
    elif isinstance(value, note.Note):
        notes = (value,)
    else:
        return ()
    result = []
    for item in notes:
        tie = getattr(item, "tie", None)
        tie_type = getattr(tie, "type", None)
        result.append(tie_type if tie_type in {"start", "stop", "continue"} else "none")
    return tuple(result)


def _music21_lyrics(value: Any) -> tuple[Lyric, ...]:
    lyrics = []
    for lyric in getattr(value, "lyrics", ()):
        lyrics.append(
            Lyric(
                text=lyric.text or "",
                number=str(getattr(lyric, "number", "1") or "1"),
                syllabic=getattr(lyric, "syllabic", None) or "single",
                extend=bool(
                    getattr(getattr(lyric, "editorial", None), "extend", False)
                ),
            )
        )
    return tuple(lyrics)


def _measure_elements(measure: stream.Measure) -> list[tuple[stream.Stream, str]]:
    voices = list(measure.getElementsByClass(stream.Voice))
    if voices:
        return [
            (voice, str(voice.id if voice.id is not None else "1")) for voice in voices
        ]
    return [(measure, "1")]


def _active_transposition(part: stream.Part, element: Any) -> Any | None:
    instruments = list(part.recurse().getElementsByClass(instrument.Instrument))
    element_offset = _fraction(element.getOffsetInHierarchy(part))
    active: tuple[Fraction, Any] | None = None
    for item in instruments:
        offset = _fraction(item.getOffsetInHierarchy(part))
        if offset <= element_offset and (active is None or offset >= active[0]):
            active = (offset, getattr(item, "transposition", None))
    return active[1] if active else None


def _clef_contexts(
    part: stream.Part, part_index: int, details: dict[str, Any] | None
) -> list[StaffContext]:
    if details is not None:
        source = details["staves"].get(part_index, {})
        if source:
            return list(source.values())
    result: dict[str, StaffContext] = {}
    for item in part.recurse().getElementsByClass(clef.Clef):
        number = str(getattr(item, "number", None) or "1")
        result.setdefault(
            number,
            StaffContext(
                number=number,
                clef_sign=getattr(item, "sign", None),
                clef_line=getattr(item, "line", None),
                clef_octave_change=int(getattr(item, "octaveChange", 0) or 0),
            ),
        )
    return list(result.values())


def _part_transposition(part: stream.Part) -> Any | None:
    for item in part.recurse().getElementsByClass(instrument.Instrument):
        transposition = getattr(item, "transposition", None)
        if transposition is not None:
            return transposition
    return None


def _key_for_measure(measure: stream.Measure) -> Any | None:
    found = list(measure.recurse().getElementsByClass(key.KeySignature))
    return found[0] if found else None


def _time_for_measure(measure: stream.Measure) -> Any | None:
    found = list(measure.recurse().getElementsByClass(meter.TimeSignature))
    return found[0] if found else None


def _source_title(details: dict[str, Any] | None) -> str:
    if details and details["titles"]:
        return details["titles"][0]
    return ""


def _measure_contexts(
    parts: list[stream.Part], details: dict[str, Any] | None
) -> list[MeasureContext]:
    part_measures = [list(part.getElementsByClass(stream.Measure)) for part in parts]
    count = max((len(measures) for measures in part_measures), default=0)
    result: list[MeasureContext] = []
    active_fifths: int | None = None
    active_mode: str | None = None
    active_beats: int | None = None
    active_beat_type: int | None = None

    for index in range(count):
        measures = [items[index] for items in part_measures if index < len(items)]
        key_signature = next(
            (
                _key_for_measure(item)
                for item in measures
                if _key_for_measure(item) is not None
            ),
            None,
        )
        time_signature = next(
            (
                _time_for_measure(item)
                for item in measures
                if _time_for_measure(item) is not None
            ),
            None,
        )
        if key_signature is not None:
            active_fifths = int(getattr(key_signature, "sharps", 0))
            active_mode = getattr(key_signature, "mode", None)
        if time_signature is not None:
            active_beats = int(time_signature.numerator)
            active_beat_type = int(time_signature.denominator)

        pickup = (
            any(
                details["pickups"].get((part_index, index), False)
                for part_index in range(len(parts))
            )
            if details
            else False
        )
        pickup = pickup or any(
            bool(getattr(item, "paddingLeft", 0)) for item in measures
        )
        nominal = None
        if active_beats is not None and active_beat_type:
            nominal = Fraction(active_beats * 4, active_beat_type)
        observed = max(
            (_fraction(item.duration.quarterLength) for item in measures),
            default=Fraction(0),
        )
        duration = observed if pickup or nominal is None else nominal
        number = (
            str(getattr(measures[0], "number", index + 1))
            if measures
            else str(index + 1)
        )
        result.append(
            MeasureContext(
                index=index,
                number=number,
                duration=duration,
                fifths=active_fifths,
                mode=active_mode,
                beats=active_beats,
                beat_type=active_beat_type,
                pickup=pickup,
            )
        )
    return result


def _clef_directions(
    parts: list[stream.Part], details: dict[str, Any] | None
) -> list[ScoreDirection]:
    directions: list[ScoreDirection] = []
    for part_index, part in enumerate(parts):
        part_id = (
            details["part_info"][part_index][0]
            if details and part_index < len(details["part_info"])
            else str(part.id)
        )
        measures = list(part.getElementsByClass(stream.Measure))
        for measure_index, measure in enumerate(measures):
            source_clefs = (
                details["clefs"].get((part_index, measure_index), []) if details else []
            )
            if source_clefs:
                changes = source_clefs
            elif details is None:
                changes = [
                    (
                        _fraction(item.getOffsetInHierarchy(measure)),
                        str(getattr(item, "number", None) or "1"),
                        getattr(item, "sign", None),
                        getattr(item, "line", None),
                        int(getattr(item, "octaveChange", 0) or 0),
                    )
                    for item in measure.recurse().getElementsByClass(clef.Clef)
                ]
            else:
                changes = []
            for onset, staff_number, sign, line, octave_change in changes:
                if sign is None:
                    continue
                line_value = "" if line is None else str(line)
                value = f"{sign}:{line_value}:{octave_change}"
                directions.append(
                    ScoreDirection(
                        measure_index=measure_index,
                        onset=onset,
                        kind="clef",
                        value=value,
                        part_id=part_id,
                        staff_number=staff_number,
                    )
                )
    return directions


def _score_title(score: stream.Score, details: dict[str, Any] | None) -> str:
    metadata = getattr(score, "metadata", None)
    title = getattr(metadata, "title", None) if metadata is not None else None
    return str(title or _source_title(details))


def _score_directions(
    parts: list[stream.Part],
) -> tuple[list[ScoreDirection], float | None]:
    directions: list[ScoreDirection] = []
    tempo_bpm: float | None = None
    seen: set[tuple[int, Fraction, str, str]] = set()
    for part in parts:
        measures = list(part.getElementsByClass(stream.Measure))
        for measure_index, measure in enumerate(measures):
            for item in measure.recurse():
                kind: str | None = None
                value: str | None = None
                if isinstance(item, tempo.MetronomeMark):
                    qpm = item.getQuarterBPM()
                    if qpm is not None:
                        value = str(qpm)
                        kind = "tempo"
                        if tempo_bpm is None:
                            tempo_bpm = float(qpm)
                elif isinstance(item, dynamics.Dynamic):
                    kind = "dynamic"
                    value = str(item.value)
                elif isinstance(item, expressions.TextExpression):
                    kind = "words"
                    value = str(item.content)
                if kind is None or not value:
                    continue
                onset = _fraction(item.getOffsetInHierarchy(measure))
                key_value = (measure_index, onset, kind, value)
                if key_value not in seen:
                    seen.add(key_value)
                    directions.append(ScoreDirection(measure_index, onset, kind, value))
    return directions, tempo_bpm


def score_to_model(
    score: stream.Score, source_musicxml: bytes | None = None
) -> ScoreModel:
    """Convert a music21 Score while retaining part, measure, voice, and event boundaries."""
    details = _source_details(source_musicxml)
    music_parts = list(score.parts)
    parts: list[ScorePart] = []
    for part_index, music_part in enumerate(music_parts):
        source_id, source_name = (
            details["part_info"][part_index]
            if details and part_index < len(details["part_info"])
            else (str(music_part.id), str(music_part.partName or music_part.id))
        )
        transposition = _part_transposition(music_part)
        transpose_semitones = (
            int(transposition.semitones) if transposition is not None else 0
        )
        model_part = ScorePart(
            id=source_id,
            name=source_name or str(music_part.partName or source_id),
            transpose_semitones=transpose_semitones,
            staves=_clef_contexts(music_part, part_index, details),
        )
        parts.append(model_part)
        part_measures = list(music_part.getElementsByClass(stream.Measure))
        for measure_index, measure in enumerate(part_measures):
            source_events = (
                details["events"].get((part_index, measure_index), [])
                if details
                else []
            )
            for container, default_voice in _measure_elements(measure):
                container_offset = (
                    Fraction(0) if container is measure else _fraction(container.offset)
                )
                for element in container.notesAndRests:
                    onset = container_offset + _fraction(element.offset)
                    is_rest = isinstance(element, note.Rest)
                    is_chord = isinstance(element, chord.Chord)
                    kind = "rest" if is_rest else "chord" if is_chord else "note"
                    written = tuple(
                        _pitch_from_music21(value)
                        for value in getattr(element, "pitches", ())
                    )
                    source_event = (
                        _match_source_event(
                            source_events, onset, default_voice, written
                        )
                        if source_events
                        else None
                    )
                    voice_id = source_event["voice"] if source_event else default_voice
                    staff_number = (
                        source_event["staff"]
                        if source_event
                        else str(getattr(element, "staffNumber", None) or "1")
                    )
                    active_transposition = _active_transposition(music_part, element)
                    sounding = tuple(
                        _pitch_from_music21(value.transpose(active_transposition))
                        if active_transposition is not None
                        else pitch_value
                        for value, pitch_value in zip(
                            getattr(element, "pitches", ()), written
                        )
                    )
                    if source_event and source_event["ties"]:
                        remaining = list(
                            zip(source_event["pitches"], source_event["ties"])
                        )
                        aligned_ties = []
                        for pitch_value in written:
                            match = next(
                                (
                                    index
                                    for index, (xml_pitch, _) in enumerate(remaining)
                                    if xml_pitch[0] == pitch_value.step
                                    and xml_pitch[2] == pitch_value.octave
                                ),
                                None,
                            )
                            if match is None:
                                aligned_ties.append("none")
                            else:
                                _, tie_value = remaining.pop(match)
                                aligned_ties.append(tie_value)
                        ties = tuple(aligned_ties)
                    else:
                        ties = _music21_ties(element)
                    if is_rest:
                        ties = ()
                    lyrics = (
                        tuple(source_event["lyrics"])
                        if source_event and source_event["lyrics"]
                        else _music21_lyrics(element)
                    )
                    model_part.events.append(
                        ScoreEvent(
                            part_id=source_id,
                            measure_index=measure_index,
                            voice_id=voice_id,
                            onset=onset,
                            duration=_fraction(element.duration.quarterLength),
                            kind=kind,
                            pitches=written,
                            sounding_pitches=sounding,
                            pitch_ties=ties,
                            staff_number=staff_number,
                            slurs=(
                                tuple(dict.fromkeys(source_event["slurs"]))
                                if source_event
                                else ()
                            ),
                            lyrics=lyrics,
                            grace=bool(getattr(element.duration, "isGrace", False)),
                            source_location=SourceLocation(
                                measure_number=str(
                                    getattr(measure, "number", measure_index + 1)
                                )
                            ),
                        )
                    )
    directions, tempo_bpm = _score_directions(music_parts)
    directions.extend(_clef_directions(music_parts, details))
    return ScoreModel(
        title=_score_title(score, details),
        parts=parts,
        measures=_measure_contexts(music_parts, details),
        tempo_bpm=tempo_bpm,
        directions=directions,
        source_musicxml=source_musicxml,
    )


def load_musicxml(path: str | Path) -> ScoreModel:
    """Parse a MusicXML or compressed MXL file directly with music21."""
    source_path = Path(path)
    source_bytes = source_path.read_bytes()
    score = converter.parse(str(source_path))
    return score_to_model(score, source_musicxml=source_bytes)



def _normalized_part_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).split()).casefold()


def _page_music21_score(page: ScoreModel) -> stream.Score:
    """Parse one page's retained source, failing closed on ambiguous structure."""
    source = page.source_musicxml
    if not source:
        raise ValueError("every page must retain its source MusicXML")
    root = _xml_root(source)
    details = _source_details(source)
    if root is None or _local_name(root) != "score-partwise" or details is None:
        raise ValueError("page source must be valid partwise MusicXML")

    source_parts = details["part_info"]
    model_names = [_normalized_part_name(part.name) for part in page.parts]
    source_names = [_normalized_part_name(name) for _, name in source_parts]
    source_ids = [part_id for part_id, _ in source_parts]
    if (
        not model_names
        or any(not name for name in model_names)
        or len(set(model_names)) != len(model_names)
        or len(set(source_ids)) != len(source_ids)
        or model_names != source_names
        or [part.id for part in page.parts] != source_ids
    ):
        raise ValueError("page part identity does not match its MusicXML source")

    suffix = ".mxl" if zipfile.is_zipfile(BytesIO(source)) else ".musicxml"
    try:
        with tempfile.TemporaryDirectory(prefix="musicxml-page-") as directory:
            source_path = Path(directory) / f"page{suffix}"
            source_path.write_bytes(source)
            score = converter.parse(str(source_path))
    except Exception as error:
        raise ValueError("page source MusicXML could not be parsed") from error

    if len(score.parts) != len(page.parts):
        raise ValueError("page MusicXML part structure is ambiguous")
    part_measure_counts = [
        len(part.getElementsByClass(stream.Measure)) for part in score.parts
    ]
    if (
        not part_measure_counts
        or len(set(part_measure_counts)) != 1
        or part_measure_counts[0] != len(page.measures)
        or not page.measures
    ):
        raise ValueError("page parts do not have the same complete measure structure")
    for part_model in page.parts:
        if any(
            event.part_id != part_model.id
            or event.measure_index < 0
            or event.measure_index >= len(page.measures)
            for event in part_model.events
        ):
            raise ValueError("page event structure does not match its part")
    return score


def _boundary_tie_marks(
    part: ScorePart, measure_index: int, measure_duration: Fraction, outgoing: bool
) -> list[tuple[tuple[str, str, Pitch], ScoreEvent]]:
    marks: list[tuple[tuple[str, str, Pitch], ScoreEvent]] = []
    for event in part.events:
        if event.measure_index != measure_index:
            continue
        if outgoing:
            if event.onset + event.duration != measure_duration:
                continue
            tie_types = {"start", "continue"}
        else:
            if event.onset != 0:
                continue
            tie_types = {"stop", "continue"}
        for pitch, tie_type in zip(event.pitches, event.pitch_ties):
            if tie_type in tie_types:
                marks.append(((event.voice_id, event.staff_number, pitch), event))
    return marks


def merge_page_models(page_models: list[ScoreModel]) -> ScoreModel:
    """Merge ordered page models after validating part identity and source structure."""
    if not page_models:
        raise ValueError("at least one page model is required")

    scores = [_page_music21_score(page) for page in page_models]
    first_names = [_normalized_part_name(part.name) for part in page_models[0].parts]
    if len(set(first_names)) != len(first_names):
        raise ValueError("part names must be unique within each page")
    for page in page_models[1:]:
        names = [_normalized_part_name(part.name) for part in page.parts]
        if len(set(names)) != len(names) or names != first_names:
            raise ValueError("page part names must be unique and in the same order")
        for first_part, other_part in zip(page_models[0].parts, page.parts):
            if first_part.transpose_semitones != other_part.transpose_semitones:
                raise ValueError("part transposition differs between pages")

    page_offsets: list[int] = []
    total_measures = 0
    for page in page_models:
        page_offsets.append(total_measures)
        total_measures += len(page.measures)

    active_fifths: int | None = None
    active_mode: str | None = None
    active_beats: int | None = None
    active_beat_type: int | None = None
    measures: list[MeasureContext] = []
    parts = [
        ScorePart(
            id=part.id,
            name=part.name,
            transpose_semitones=part.transpose_semitones,
            staves=deepcopy(part.staves),
        )
        for part in page_models[0].parts
    ]
    directions: list[ScoreDirection] = []
    review_issues: list[ReviewIssue] = []
    tempo_bpm = next(
        (page.tempo_bpm for page in page_models if page.tempo_bpm is not None), None
    )
    requires_review = any(page.requires_review for page in page_models)

    for page_index, page in enumerate(page_models):
        offset = page_offsets[page_index]
        for local_index, measure in enumerate(page.measures):
            if measure.fifths is not None:
                active_fifths = measure.fifths
            if measure.mode is not None:
                active_mode = measure.mode
            if measure.beats is not None:
                active_beats = measure.beats
            if measure.beat_type is not None:
                active_beat_type = measure.beat_type
            measures.append(
                replace(
                    measure,
                    index=offset + local_index,
                    number=str(offset + local_index + 1),
                    fifths=active_fifths,
                    mode=active_mode,
                    beats=active_beats,
                    beat_type=active_beat_type,
                )
            )

        canonical_ids = {
            part.id: parts[index].id for index, part in enumerate(page.parts)
        }
        for part_index, page_part in enumerate(page.parts):
            output_part = parts[part_index]
            for event in page_part.events:
                old_location = event.source_location
                local_measure_number = page.measures[event.measure_index].number
                location = SourceLocation(
                    page=page_index + 1,
                    system=old_location.system if old_location else None,
                    measure_number=(
                        old_location.measure_number
                        if old_location and old_location.measure_number is not None
                        else local_measure_number
                    ),
                )
                output_part.events.append(
                    replace(
                        event,
                        part_id=output_part.id,
                        measure_index=offset + event.measure_index,
                        source_location=location,
                    )
                )

        for direction in page.directions:
            if direction.measure_index < 0 or direction.measure_index >= len(page.measures):
                raise ValueError("page direction is outside its measure structure")
            if direction.part_id is not None and direction.part_id not in canonical_ids:
                raise ValueError("page direction references an unknown part")
            directions.append(
                replace(
                    direction,
                    measure_index=offset + direction.measure_index,
                    part_id=(
                        canonical_ids[direction.part_id]
                        if direction.part_id is not None
                        else None
                    ),
                )
            )

        for issue in page.review_issues:
            location = issue.location
            if location is not None:
                local_number = location.measure_number
                if local_number is None and page.measures:
                    local_number = page.measures[0].number
                location = replace(location, page=page_index + 1, measure_number=local_number)
            review_issues.append(replace(issue, location=location))

    for page_index in range(len(page_models) - 1):
        left, right = page_models[page_index : page_index + 2]
        left_measure = len(left.measures) - 1
        right_measure = 0
        for part_index, left_part in enumerate(left.parts):
            right_part = right.parts[part_index]
            outgoing = _boundary_tie_marks(
                left_part, left_measure, left.measures[left_measure].duration, True
            )
            incoming = _boundary_tie_marks(
                right_part, right_measure, right.measures[right_measure].duration, False
            )
            remaining_incoming = list(incoming)
            for mark, event in outgoing:
                match = next(
                    (index for index, (other_mark, _) in enumerate(remaining_incoming)
                     if other_mark == mark),
                    None,
                )
                if match is not None:
                    remaining_incoming.pop(match)
                    continue
                location = SourceLocation(
                    page=page_index + 1,
                    system=(event.source_location.system if event.source_location else None),
                    measure_number=(
                        event.source_location.measure_number
                        if event.source_location
                        else left.measures[left_measure].number
                    ),
                )
                review_issues.append(
                    ReviewIssue(
                        "page_boundary_tie_unresolved",
                        f"Tie at the end of page {page_index + 1} has no matching start on page {page_index + 2}.",
                        location,
                        candidates=(f"page {page_index + 2}",),
                    )
                )
                requires_review = True
            for _mark, event in remaining_incoming:
                location = SourceLocation(
                    page=page_index + 2,
                    system=(event.source_location.system if event.source_location else None),
                    measure_number=(
                        event.source_location.measure_number
                        if event.source_location
                        else right.measures[0].number
                    ),
                )
                review_issues.append(
                    ReviewIssue(
                        "page_boundary_tie_unresolved",
                        f"Tie at the start of page {page_index + 2} has no matching stop on page {page_index + 1}.",
                        location,
                        candidates=(f"page {page_index + 1}",),
                    )
                )
                requires_review = True

    merged_score = stream.Score()
    merged_score.metadata = deepcopy(getattr(scores[0], "metadata", None))
    if merged_score.metadata is not None and page_models[0].title:
        merged_score.metadata.title = page_models[0].title
    for part_index, first_music_part in enumerate(scores[0].parts):
        combined_part = deepcopy(first_music_part)
        for original_measure in list(
            combined_part.getElementsByClass(stream.Measure)
        ):
            combined_part.remove(original_measure)
        for page_index, score in enumerate(scores):
            source_measures = list(
                score.parts[part_index].getElementsByClass(stream.Measure)
            )
            for local_index, source_measure in enumerate(source_measures):
                measure = deepcopy(source_measure)
                measure.number = page_offsets[page_index] + local_index + 1
                combined_part.append(measure)
        merged_score.insert(0, combined_part)

    for part_index, model_part in enumerate(parts):
        music_part = merged_score.parts[part_index]
        open_slurs: dict[str, Any] = {}
        used_elements: set[int] = set()
        for event in sorted(
            model_part.events,
            key=lambda item: (item.measure_index, item.onset, item.voice_id),
        ):
            if not event.slurs:
                continue
            measure = list(music_part.getElementsByClass(stream.Measure))[event.measure_index]
            element = next(
                (
                    candidate
                    for candidate in measure.recurse().notes
                    if id(candidate) not in used_elements
                    and _fraction(candidate.getOffsetInHierarchy(measure)) == event.onset
                    and tuple(
                        _pitch_from_music21(pitch)
                        for pitch in getattr(candidate, "pitches", ())
                    ) == event.pitches
                    and (
                        (event.kind == "note" and isinstance(candidate, note.Note))
                        or (event.kind == "chord" and isinstance(candidate, chord.Chord))
                    )
                ),
                None,
            )
            if element is None:
                raise ValueError("slur event cannot be matched to the MusicXML source")
            used_elements.add(id(element))
            for slur_type, number in event.slurs:
                if slur_type == "start":
                    open_slurs[number] = element
                elif slur_type == "stop" and number in open_slurs:
                    merged_score.insert(0, spanner.Slur(open_slurs.pop(number), element))
                elif slur_type == "continue" and number in open_slurs:
                    merged_score.insert(0, spanner.Slur(open_slurs[number], element))
                    open_slurs[number] = element

    with tempfile.TemporaryDirectory(prefix="musicxml-merged-") as directory:
        output_path = Path(directory) / "merged.musicxml"
        merged_score.write("musicxml", fp=str(output_path))
        source_musicxml = output_path.read_bytes()

    return ScoreModel(
        title=page_models[0].title,
        parts=parts,
        measures=measures,
        tempo_bpm=tempo_bpm,
        directions=directions,
        source_musicxml=source_musicxml,
        requires_review=requires_review,
        review_issues=review_issues,
    )
