"""Paginated Jianpu PDF rendering from a validated score model."""

from __future__ import annotations

import hashlib
import os
import unicodedata
from fractions import Fraction
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from src.music_convert.jianpu import map_pitch
from src.music_convert.model import Pitch, ScoreEvent, ScoreModel
from src.music_convert.validation import validate_score

_MAJOR_TONICS = {
    -7: "Cb",
    -6: "Gb",
    -5: "Db",
    -4: "Ab",
    -3: "Eb",
    -2: "Bb",
    -1: "F",
    0: "C",
    1: "G",
    2: "D",
    3: "A",
    4: "E",
    5: "B",
    6: "F#",
    7: "C#",
}
_MINOR_TONICS = {
    -7: "Ab",
    -6: "Eb",
    -5: "Bb",
    -4: "F",
    -3: "C",
    -2: "G",
    -1: "D",
    0: "A",
    1: "E",
    2: "B",
    3: "F#",
    4: "C#",
    5: "G#",
    6: "D#",
    7: "A#",
}


def _movable_contexts(
    score: ScoreModel, tonic: str | None
) -> dict[int, tuple[str, str]]:
    contexts: dict[int, tuple[str, str]] = {}
    active_mode: str | None = None
    active_fifths: int | None = None
    for measure in sorted(score.measures, key=lambda item: item.index):
        if measure.mode is not None:
            if measure.mode not in ("major", "minor"):
                raise ValueError(f"missing_key_mode: unsupported mode {measure.mode!r}")
            active_mode = measure.mode
        if measure.fifths is not None:
            active_fifths = measure.fifths
        if active_mode is None:
            raise ValueError(
                "missing_key_mode: movable notation requires a model key mode"
            )

        measure_tonic = tonic
        if measure_tonic is None:
            if active_fifths is None:
                raise ValueError(
                    "missing_tonic: movable notation requires a model key signature"
                )
            key_table = _MAJOR_TONICS if active_mode == "major" else _MINOR_TONICS
            measure_tonic = key_table.get(active_fifths)
            if measure_tonic is None:
                raise ValueError(
                    f"missing_tonic: unsupported key signature {active_fifths}"
                )
        contexts[measure.index] = (measure_tonic, active_mode)
    return contexts


def _mapped_pitches(
    event: ScoreEvent,
    *,
    notation: str,
    context: tuple[str, str] | None,
) -> list[tuple[str, int]]:
    if event.kind == "rest":
        return []
    event_tonic, key_mode = context if context is not None else (None, None)
    return [
        map_pitch(
            pitch,
            tonic=event_tonic,
            key_mode=key_mode,
            notation=notation,
        )
        for pitch in event.effective_sounding_pitches
    ]


def _event_token(
    event: ScoreEvent,
    *,
    notation: str,
    context: tuple[str, str] | None,
) -> str:
    if event.kind == "rest":
        return "0"
    return "+".join(
        degree
        for degree, _octave in _mapped_pitches(
            event, notation=notation, context=context
        )
    )


def _duration_marks(duration: Fraction) -> tuple[int, int, int]:
    """Return augmentation dots, underlines, and duration dashes exactly."""
    if isinstance(duration, bool) or not isinstance(duration, (Fraction, int)):
        raise TypeError(f"duration {duration!r} is not an exact rational value")
    duration = Fraction(duration)
    for exponent in range(-8, 17):
        base = Fraction(2**exponent) if exponent >= 0 else Fraction(1, 2**-exponent)
        for dots in range(4):
            dot_factor = Fraction(2 ** (dots + 1) - 1, 2**dots)
            if duration == base * dot_factor:
                return dots, max(0, -exponent), max(0, exponent)
    raise ValueError(
        f"duration {duration} cannot be represented faithfully as a "
        "power-of-two Jianpu value with up to 3 dots"
    )


def _contains_cjk(text: str) -> bool:
    script_name_prefixes = (
        "CJK UNIFIED IDEOGRAPH-",
        "CJK COMPATIBILITY IDEOGRAPH-",
        "HIRAGANA",
        "KATAKANA",
        "HALFWIDTH KATAKANA",
        "HANGUL",
        "BOPOMOFO",
        "KANGXI RADICAL",
        "IDEOGRAPHIC",
    )
    return any(
        unicodedata.name(char, "").startswith(script_name_prefixes)
        or 0x3000 <= ord(char) <= 0x303F
        or (
            unicodedata.east_asian_width(char) in {"W", "F"}
            and unicodedata.category(char)[0] in {"P", "S"}
        )
        for char in text
    )


def _lyrics_font(score: ScoreModel, font_path: str | Path | None) -> str:
    lyric_texts = [
        lyric.text
        for part in score.parts
        for event in part.events
        for lyric in event.lyrics
    ]
    if not any(_contains_cjk(text) for text in lyric_texts):
        return "Helvetica"

    configured_path = font_path or os.environ.get("JIANPU_CJK_FONT")
    if not configured_path:
        raise RuntimeError(
            "CJK lyrics require an explicit font_path or JIANPU_CJK_FONT setting"
        )
    path = Path(configured_path).expanduser()
    if not path.is_file():
        raise RuntimeError(
            f"CJK font configured by font_path/JIANPU_CJK_FONT does not exist: {path}"
        )

    font_name = (
        "JianpuCJK_"
        + hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    )
    try:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(path)))
        registered_font = pdfmetrics.getFont(font_name)
        character_map = registered_font.face.charToGlyph
        missing_characters = sorted(
            {
                char
                for text in lyric_texts
                for char in text
                if character_map.get(ord(char), 0) == 0
            },
            key=ord,
        )
        if missing_characters:
            missing = ", ".join(
                f"{char!r} (U+{ord(char):04X})" for char in missing_characters
            )
            raise RuntimeError(
                f"configured CJK font is missing required glyphs: {missing}"
            )
        for text in lyric_texts:
            stringWidth(text, font_name, 8)
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(
            f"CJK font configured by font_path/JIANPU_CJK_FONT cannot render lyrics: {path}"
        ) from error
    return font_name


def _pitch_number(pitch: Pitch) -> int:
    natural = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return 12 * pitch.octave + natural[pitch.step] + pitch.alter


def _tie_pairs(score: ScoreModel):
    measure_starts: dict[int, Fraction] = {}
    absolute_start = Fraction(0)
    for measure in sorted(score.measures, key=lambda item: item.index):
        measure_starts[measure.index] = absolute_start
        absolute_start += measure.duration

    result = []
    for part_index, part in enumerate(score.parts):
        timed: dict[tuple[str, str, Fraction], list[ScoreEvent]] = {}
        absolute_onsets: dict[int, Fraction] = {}
        for event in part.events:
            absolute_onset = measure_starts[event.measure_index] + event.onset
            absolute_onsets[id(event)] = absolute_onset
            key = (event.staff_number, event.voice_id, absolute_onset)
            timed.setdefault(key, []).append(event)

        for event in part.events:
            if event.kind == "rest":
                continue
            states = event.pitch_ties or ("none",) * len(event.pitches)
            for pitch_index, state in enumerate(states):
                if state not in ("start", "continue"):
                    continue
                sounding_pitch = event.effective_sounding_pitches[pitch_index]
                expected_onset = absolute_onsets[id(event)] + event.duration
                candidates = timed.get(
                    (event.staff_number, event.voice_id, expected_onset), []
                )
                matches = []
                for target in candidates:
                    if target.kind == "rest":
                        continue
                    target_states = target.pitch_ties or ("none",) * len(target.pitches)
                    for target_index, target_pitch in enumerate(
                        target.effective_sounding_pitches
                    ):
                        if _pitch_number(target_pitch) == _pitch_number(
                            sounding_pitch
                        ) and target_states[target_index] in ("stop", "continue"):
                            matches.append((target, target_index))
                if len(matches) != 1:
                    raise ValueError(
                        "validated tie could not be paired with one exact next event "
                        "in its staff and voice"
                    )
                target, target_index = matches[0]
                result.append((part_index, event, target, pitch_index, target_index))
    return result


def _slur_pairs(score: ScoreModel):
    result = []
    for part_index, part in enumerate(score.parts):
        lanes: dict[tuple[str, str], list[ScoreEvent]] = {}
        for event in part.events:
            lanes.setdefault((event.staff_number, event.voice_id), []).append(event)
        for lane, events in lanes.items():
            ordered = sorted(
                events,
                key=lambda event: (event.measure_index, event.onset, event.duration),
            )
            active: dict[str, ScoreEvent] = {}
            for event in ordered:
                marks = event.slurs
                for state, number in marks:
                    if state not in ("stop", "continue"):
                        continue
                    source = active.pop(number, None)
                    if source is None:
                        raise ValueError(
                            f"slur {number!r} stops without a matching start in "
                            f"part {part.id}, staff {lane[0]}, voice {lane[1]}"
                        )
                    if source is event:
                        raise ValueError(
                            "slur continuation cannot start and stop on one event"
                        )
                    result.append((part_index, source, event))
                for state, number in marks:
                    if state not in ("start", "continue"):
                        continue
                    if number in active:
                        raise ValueError(
                            f"slur {number!r} starts twice before it stops in "
                            f"part {part.id}, staff {lane[0]}, voice {lane[1]}"
                        )
                    active[number] = event
            if active:
                number = next(iter(active))
                raise ValueError(
                    f"slur {number!r} has no matching stop in "
                    f"part {part.id}, staff {lane[0]}, voice {lane[1]}"
                )
    return result


def _measure_groups(measures, maximum, relationships):
    if not measures:
        return [[]]
    measure_positions = {
        measure.index: position for position, measure in enumerate(measures)
    }
    intervals = sorted(
        (
            measure_positions[source.measure_index],
            measure_positions[target.measure_index],
        )
        for source, target in relationships
    )
    linked_components: list[list[int]] = []
    for start, stop in intervals:
        if linked_components and start <= linked_components[-1][1]:
            linked_components[-1][1] = max(linked_components[-1][1], stop)
        else:
            linked_components.append([start, stop])

    for start, stop in linked_components:
        component_size = stop - start + 1
        if component_size > maximum:
            raise ValueError(
                "linked tie/slur chain spans "
                f"{component_size} measures, exceeding the system limit of {maximum}"
            )

    groups = []
    offset = 0
    while offset < len(measures):
        end = min(offset + maximum, len(measures))
        for start, stop in linked_components:
            if start < end <= stop:
                end = start
                break
        if end <= offset:
            raise ValueError(
                "linked tie/slur chain cannot be placed in a rendered system"
            )
        groups.append(measures[offset:end])
        offset = end
    return groups


def _pitch_center(x: float, degrees: list[tuple[str, int]], pitch_index: int) -> float:
    prefix = "+".join(degree for degree, _octave in degrees[:pitch_index])
    prefix_width = stringWidth(prefix + ("+" if prefix else ""), "Helvetica", 11)
    degree = degrees[pitch_index][0]
    return x + prefix_width + stringWidth(degree, "Helvetica", 11) / 2


def event_x(
    onset: Fraction,
    measure_duration: Fraction,
    measure_x: float,
    measure_width: float,
) -> float:
    """Return a beat-proportional x coordinate within a measure."""
    if measure_duration <= 0:
        raise ValueError("measure_duration must be positive")
    return measure_x + float(onset / measure_duration) * measure_width


def render_jianpu_pdf(
    score: ScoreModel,
    output_path: str | Path,
    *,
    notation: str = "movable",
    tonic: str | None = None,
    title: str | None = None,
    font_path: str | Path | None = None,
) -> Path:
    """Render paginated Jianpu notation with exact rhythm and lyrics."""
    if notation not in ("movable", "fixed"):
        raise ValueError("notation must be 'movable' or 'fixed'")

    issues = validate_score(score)
    if issues:
        codes = ", ".join(dict.fromkeys(issue.code for issue in issues))
        raise ValueError(f"score validation failed: {codes}")

    contexts = _movable_contexts(score, tonic) if notation == "movable" else {}
    lyrics_font = _lyrics_font(score, font_path)
    measures = sorted(score.measures, key=lambda item: item.index)
    page_width, page_height = landscape(A4)
    document_title = score.title if title is None else title
    system_x = 150.0
    system_right = page_width - 36.0
    available_width = system_right - system_x
    minimum_measure_width = 80.0
    measures_per_system = max(1, int(available_width // minimum_measure_width))
    tie_pairs = _tie_pairs(score)
    slur_pairs = _slur_pairs(score)
    linked_events = [
        (source, target)
        for _part_index, source, target, _source_pitch, _target_pitch in tie_pairs
    ] + [(source, target) for _part_index, source, target in slur_pairs]
    measure_groups = _measure_groups(measures, measures_per_system, linked_events)

    part_lane_keys = [
        sorted({(event.staff_number, event.voice_id) for event in part.events})
        for part in score.parts
    ]
    lane_lyric_numbers = []
    for part in score.parts:
        by_lane: dict[tuple[str, str], set[str]] = {}
        for event in part.events:
            lane = (event.staff_number, event.voice_id)
            by_lane.setdefault(lane, set()).update(
                lyric.number for lyric in event.lyrics
            )
        lane_lyric_numbers.append(
            {lane: tuple(sorted(numbers)) for lane, numbers in by_lane.items()}
        )
    row_padding = 18.0
    minimum_row_height = 54.0
    lane_vertical_extents = []
    lane_offsets_by_part = []
    row_heights = []
    for part_index, lane_keys in enumerate(part_lane_keys):
        part = score.parts[part_index]
        extents: dict[tuple[str, str], list[float]] = {
            lane: [8.0, 0.0] for lane in lane_keys
        }
        for event in part.events:
            lane = (event.staff_number, event.voice_id)
            above, below = extents[lane]
            if not event.grace:
                _dots, underlines, _dashes = _duration_marks(event.duration)
                if underlines:
                    below = max(below, 2.0 + (underlines - 1) * 2.5 + 0.5)
            if event.lyrics:
                verse_numbers = lane_lyric_numbers[part_index][lane]
                for lyric in event.lyrics:
                    verse_index = verse_numbers.index(lyric.number)
                    below = max(below, 22.0 + verse_index * 9.0)
            if any(state != "none" for state in event.pitch_ties):
                below = max(below, 10.7)
            for _degree, octave in _mapped_pitches(
                event, notation=notation, context=contexts.get(event.measure_index)
            ):
                if octave > 0:
                    above = max(above, 10.0 + (octave - 1) * 3.5 + 1.2)
                elif octave < 0:
                    below = max(below, 10.0 + (abs(octave) - 1) * 3.5 + 1.2)
            extents[lane] = [above, below]

        for part_slur_index, source, target in slur_pairs:
            if part_slur_index != part_index:
                continue
            lane = (source.staff_number, source.voice_id)
            high_marks = [
                10.0 + (octave - 1) * 3.5 + 1.2
                for event in part.events
                if event.staff_number == lane[0]
                and event.voice_id == lane[1]
                and (source.measure_index, source.onset)
                <= (event.measure_index, event.onset)
                <= (target.measure_index, target.onset)
                for _degree, octave in _mapped_pitches(
                    event,
                    notation=notation,
                    context=contexts.get(event.measure_index),
                )
                if octave > 0
            ]
            above, below = extents[lane]
            above = max(above, max([14.0, *(mark + 7.7 for mark in high_marks)]))
            extents[lane] = [above, below]
        lane_vertical_extents.append(extents)

        lane_offsets: dict[tuple[str, str], float] = {}
        next_offset = 0.0
        for lane_index, lane in enumerate(lane_keys):
            lane_offsets[lane] = next_offset
            if lane_index + 1 < len(lane_keys):
                next_lane = lane_keys[lane_index + 1]
                next_offset += max(
                    22.0,
                    extents[lane][1] + extents[next_lane][0] + 3.0,
                )
        lane_offsets_by_part.append(lane_offsets)
        if lane_keys:
            last_lane = lane_keys[-1]
            first_lane = lane_keys[0]
            row_height = (
                next_offset
                + extents[last_lane][1]
                + max(row_padding, extents[first_lane][0] + 3.0)
            )
        else:
            row_height = minimum_row_height
        row_heights.append(max(minimum_row_height, row_height))
    available_height = page_height - 86.0 - 36.0
    ensemble_height = sum(row_heights)
    if ensemble_height > available_height:
        raise ValueError(
            "ensemble lane layout cannot fit on a landscape page; "
            "reduce the number of parts or lanes"
        )

    def require_text_fits(text: str, font_name: str, font_size: float, width: float):
        if stringWidth(text, font_name, font_size) > width:
            raise ValueError(f"text {text!r} cannot fit within its horizontal bounds")

    require_text_fits(
        document_title,
        "Helvetica-Bold",
        18,
        system_right - 36.0,
    )
    for part in score.parts:
        require_text_fits(
            part.name,
            "Helvetica-Bold",
            11,
            system_x - 36.0 - 12.0,
        )

    for measure_group in measure_groups:
        measure_width = available_width / len(measure_group) if measure_group else 0.0
        measure_layout = {
            measure.index: (position, measure)
            for position, measure in enumerate(measure_group)
        }
        for position, measure in enumerate(measure_group):
            measure_x = system_x + position * measure_width
            require_text_fits(
                measure.number,
                "Helvetica",
                9,
                measure_width,
            )
        for part_index, part in enumerate(score.parts):
            lane_events: dict[tuple[str, str], list[ScoreEvent]] = {}
            for event in part.events:
                if event.measure_index in measure_layout:
                    lane_events.setdefault(
                        (event.staff_number, event.voice_id), []
                    ).append(event)

            row_y = page_height - 86.0 - sum(row_heights[:part_index])
            for lane, events in lane_events.items():
                ordered_events = sorted(
                    events,
                    key=lambda event: (
                        measure_layout[event.measure_index][0],
                        event.onset,
                    ),
                )
                lane_y = row_y - lane_offsets_by_part[part_index][lane]
                verse_numbers = lane_lyric_numbers[part_index].get(lane, ())
                for event_index, event in enumerate(ordered_events):
                    if event.grace:
                        raise ValueError(
                            "grace events are zero-duration and are not yet "
                            "rendered by this Jianpu renderer"
                        )
                    try:
                        dots, underlines, dashes = _duration_marks(event.duration)
                    except ValueError as error:
                        raise ValueError(
                            f"event at measure {event.measure_index}, onset "
                            f"{event.onset}: {error}"
                        ) from error
                    position, measure = measure_layout[event.measure_index]
                    measure_x = system_x + position * measure_width
                    x = event_x(event.onset, measure.duration, measure_x, measure_width)
                    cell_right = measure_x + measure_width
                    if event_index + 1 < len(ordered_events):
                        next_event = ordered_events[event_index + 1]
                        next_position, next_measure = measure_layout[
                            next_event.measure_index
                        ]
                        cell_right = min(
                            cell_right,
                            event_x(
                                next_event.onset,
                                next_measure.duration,
                                system_x + next_position * measure_width,
                                measure_width,
                            ),
                        )

                    token = _event_token(
                        event,
                        notation=notation,
                        context=contexts.get(event.measure_index),
                    )
                    mapped = _mapped_pitches(
                        event,
                        notation=notation,
                        context=contexts.get(event.measure_index),
                    )
                    token_width = stringWidth(token, "Helvetica", 11)
                    require_text_fits(token, "Helvetica", 11, system_right - x)
                    mark_extent = (
                        3.0 + dots * 4.0 + dashes * 8.0 if dots or dashes else 0.0
                    )
                    if x + token_width + mark_extent > cell_right:
                        raise ValueError(
                            f"event notation {token!r} cannot fit within its "
                            "rhythmic cell before a barline or following event"
                        )

                    high_octave_mark = max(
                        (
                            10.0 + (octave - 1) * 3.5 + 1.2
                            for _degree, octave in mapped
                            if octave > 0
                        ),
                        default=0.0,
                    )
                    low_octave_mark = max(
                        (
                            10.0 + (abs(octave) - 1) * 3.5 + 1.2
                            for _degree, octave in mapped
                            if octave < 0
                        ),
                        default=0.0,
                    )
                    low_underline = 2.0 + (underlines - 1) * 2.5 if underlines else 0.0
                    if lane_y + high_octave_mark > page_height - 58.0:
                        raise ValueError(
                            "octave marks exceed the system's vertical bounds"
                        )
                    if lane_y - low_octave_mark < 36.0:
                        raise ValueError(
                            "octave marks exceed the page's lower vertical bounds"
                        )
                    if (
                        lane_y - max(low_underline, 10.0 if event.lyrics else 0.0)
                        < 36.0
                    ):
                        raise ValueError("event marks exceed the page's lower bounds")

                    seen_verses: set[str] = set()
                    for lyric in event.lyrics:
                        if lyric.number in seen_verses:
                            raise ValueError(
                                f"event has multiple lyric texts for verse {lyric.number!r}"
                            )
                        seen_verses.add(lyric.number)
                        if lyric.syllabic not in ("single", "begin", "middle", "end"):
                            raise ValueError(
                                f"unsupported lyric syllabic value {lyric.syllabic!r}"
                            )
                        lyric_width = stringWidth(lyric.text, lyrics_font, 8)
                        suffix = "-" if lyric.syllabic in ("begin", "middle") else ""
                        suffix_width = stringWidth(suffix, lyrics_font, 8)
                        if lyric_width + suffix_width > cell_right - x:
                            raise ValueError(
                                f"lyric {lyric.text!r} cannot fit before the next "
                                "same-lane event or barline"
                            )
                        if (
                            lyric.extend
                            and cell_right - x - lyric_width - suffix_width < 8
                        ):
                            raise ValueError(
                                f"lyric extender for {lyric.text!r} cannot fit "
                                "before the next same-lane event or barline"
                            )
                        verse_index = verse_numbers.index(lyric.number)
                        lyric_y = lane_y - 19.0 - verse_index * 9.0
                        if lyric_y - 3.0 < 36.0 or lyric_y + 8.0 > page_height - 36.0:
                            raise ValueError("lyric exceeds the page's vertical bounds")

    for part_index, source, target, source_pitch_index, target_pitch_index in tie_pairs:
        source_group = next(
            (
                group
                for group in measure_groups
                if any(item.index == source.measure_index for item in group)
            ),
            None,
        )
        if source_group is None or not any(
            item.index == target.measure_index for item in source_group
        ):
            raise ValueError(
                "tied notes could not be placed in the same rendered system"
            )
        group_layout = {
            measure.index: (position, measure)
            for position, measure in enumerate(source_group)
        }
        source_position, source_measure = group_layout[source.measure_index]
        target_position, target_measure = group_layout[target.measure_index]
        system_measure_width = available_width / len(source_group)
        source_x = event_x(
            source.onset,
            source_measure.duration,
            system_x + source_position * system_measure_width,
            system_measure_width,
        )
        target_x = event_x(
            target.onset,
            target_measure.duration,
            system_x + target_position * system_measure_width,
            system_measure_width,
        )
        source_degrees = _mapped_pitches(
            source, notation=notation, context=contexts.get(source.measure_index)
        )
        target_degrees = _mapped_pitches(
            target, notation=notation, context=contexts.get(target.measure_index)
        )
        start_x = _pitch_center(source_x, source_degrees, source_pitch_index)
        end_x = _pitch_center(target_x, target_degrees, target_pitch_index)
        if end_x <= start_x:
            raise ValueError("tied pitches do not have increasing page positions")
        lane_y = (
            page_height
            - 86.0
            - sum(row_heights[:part_index])
            - lane_offsets_by_part[part_index][(source.staff_number, source.voice_id)]
        )
        if lane_y - 10.7 < 36.0:
            raise ValueError("tie curve exceeds the page's lower bounds")

    for part_index, source, target in slur_pairs:
        source_group = next(
            (
                group
                for group in measure_groups
                if any(item.index == source.measure_index for item in group)
            ),
            None,
        )
        if source_group is None or not any(
            item.index == target.measure_index for item in source_group
        ):
            raise ValueError(
                "slurred notes could not be placed in the same rendered system"
            )
        source_lane = (source.staff_number, source.voice_id)
        lane_y = (
            page_height
            - 86.0
            - sum(row_heights[:part_index])
            - lane_offsets_by_part[part_index][source_lane]
        )
        high_marks = [
            10.0 + (octave - 1) * 3.5 + 1.2
            for event in score.parts[part_index].events
            if event.staff_number == source.staff_number
            and event.voice_id == source.voice_id
            and (source.measure_index, source.onset)
            <= (event.measure_index, event.onset)
            <= (target.measure_index, target.onset)
            for _degree, octave in _mapped_pitches(
                event, notation=notation, context=contexts.get(event.measure_index)
            )
            if octave > 0
        ]
        slur_height = max([14.0, *(mark + 4.0 for mark in high_marks)])
        if lane_y + slur_height + 3.7 > page_height - 58.0:
            raise ValueError("slur curve exceeds the system's upper bounds")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = Canvas(str(output), pagesize=(page_width, page_height))
    pdf.setTitle(document_title)

    for page_index, page_measures in enumerate(measure_groups):
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawCentredString(page_width / 2, page_height - 42, document_title)

        measure_width = available_width / len(page_measures) if page_measures else 0.0
        measure_layout = {
            measure.index: (position, measure)
            for position, measure in enumerate(page_measures)
        }
        row_y = {
            part_index: page_height - 86.0 - sum(row_heights[:part_index])
            for part_index in range(len(score.parts))
        }

        if page_measures and score.parts:
            last_part_index = len(score.parts) - 1
            last_lane_keys = part_lane_keys[last_part_index]
            last_lane = last_lane_keys[-1] if last_lane_keys else None
            bottom_clearance = (
                lane_vertical_extents[last_part_index][last_lane][1] + 18.0
                if last_lane is not None
                else 18.0
            )
            system_top = row_y[0] + 18
            system_bottom = (
                row_y[last_part_index]
                - lane_offsets_by_part[last_part_index].get(last_lane, 0.0)
                - bottom_clearance
            )
            pdf.setFont("Helvetica", 9)
            pdf.setLineWidth(0.7)
            for position, measure in enumerate(page_measures):
                measure_x = system_x + position * measure_width
                pdf.drawString(measure_x, system_top + 4, measure.number)
                barline_x = measure_x + measure_width
                pdf.line(barline_x, system_top, barline_x, system_bottom)

        event_geometry = {}
        for part_index, part in enumerate(score.parts):
            y = row_y[part_index]
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(36, y, part.name)
            pdf.setFont("Helvetica", 11)

            lane_keys = part_lane_keys[part_index]
            lanes = lane_offsets_by_part[part_index]
            grouped_events: dict[tuple[int, str, str], list[ScoreEvent]] = {}
            for event in part.events:
                if event.measure_index not in measure_layout:
                    continue
                group_key = (event.measure_index, event.staff_number, event.voice_id)
                grouped_events.setdefault(group_key, []).append(event)

            for (measure_index, staff_number, voice_id), events in sorted(
                grouped_events.items()
            ):
                position, measure = measure_layout[measure_index]
                measure_x = system_x + position * measure_width
                lane = (staff_number, voice_id)
                lane_y = y - lanes[lane]
                verse_numbers = lane_lyric_numbers[part_index].get(lane, ())
                for event in sorted(events, key=lambda item: item.onset):
                    token = _event_token(
                        event,
                        notation=notation,
                        context=contexts.get(event.measure_index),
                    )
                    mapped = _mapped_pitches(
                        event,
                        notation=notation,
                        context=contexts.get(event.measure_index),
                    )
                    dots, underlines, dashes = _duration_marks(event.duration)
                    x = event_x(event.onset, measure.duration, measure_x, measure_width)
                    token_width = stringWidth(token, "Helvetica", 11)
                    pdf.setFont("Helvetica", 11)
                    pdf.drawString(x, lane_y, token)
                    event_geometry[id(event)] = (x, lane_y, mapped, token_width)

                    for pitch_index, (_degree, octave) in enumerate(mapped):
                        if octave == 0:
                            continue
                        center = _pitch_center(x, mapped, pitch_index)
                        direction = 1 if octave > 0 else -1
                        for level in range(abs(octave)):
                            mark_y = lane_y + direction * (10.0 + level * 3.5)
                            pdf.circle(center, mark_y, 1.2, stroke=0, fill=1)

                    for dot_index in range(dots):
                        pdf.circle(
                            x + token_width + 3.0 + dot_index * 4.0,
                            lane_y + 3.0,
                            1.2,
                            stroke=0,
                            fill=1,
                        )
                    dash_start = x + token_width + 3.0 + dots * 4.0
                    for dash_index in range(dashes):
                        dash_x = dash_start + dash_index * 8.0
                        pdf.line(dash_x, lane_y + 3.0, dash_x + 6.0, lane_y + 3.0)
                    for underline_index in range(underlines):
                        underline_y = lane_y - 2.0 - underline_index * 2.5
                        pdf.line(x, underline_y, x + token_width, underline_y)

                    cell_right = measure_x + measure_width
                    next_events = sorted(events, key=lambda item: item.onset)
                    event_position = next_events.index(event)
                    if event_position + 1 < len(next_events):
                        next_event = next_events[event_position + 1]
                        cell_right = min(
                            cell_right,
                            event_x(
                                next_event.onset,
                                measure.duration,
                                measure_x,
                                measure_width,
                            ),
                        )
                    for lyric in event.lyrics:
                        verse_index = verse_numbers.index(lyric.number)
                        lyric_y = lane_y - 19.0 - verse_index * 9.0
                        pdf.setFont(lyrics_font, 8)
                        pdf.drawString(x, lyric_y, lyric.text)
                        lyric_width = stringWidth(lyric.text, lyrics_font, 8)
                        suffix = "-" if lyric.syllabic in ("begin", "middle") else ""
                        suffix_width = stringWidth(suffix, lyrics_font, 8)
                        if suffix:
                            pdf.drawString(x + lyric_width, lyric_y, suffix)
                        if lyric.extend:
                            extender_start = x + lyric_width + suffix_width + 2.0
                            pdf.line(
                                extender_start,
                                lyric_y + 2.0,
                                cell_right - 2.0,
                                lyric_y + 2.0,
                            )

        for (
            part_index,
            source,
            target,
            source_pitch_index,
            target_pitch_index,
        ) in tie_pairs:
            if source.measure_index not in measure_layout:
                continue
            source_x, source_y, source_mapped, _source_width = event_geometry[
                id(source)
            ]
            target_x, _target_y, target_mapped, _target_width = event_geometry[
                id(target)
            ]
            start_x = _pitch_center(source_x, source_mapped, source_pitch_index)
            end_x = _pitch_center(target_x, target_mapped, target_pitch_index)
            tie_y = source_y - 7.0
            path = pdf.beginPath()
            path.moveTo(start_x, tie_y)
            path.curveTo(
                start_x + (end_x - start_x) / 3.0,
                tie_y - 3.0,
                start_x + 2.0 * (end_x - start_x) / 3.0,
                tie_y - 3.0,
                end_x,
                tie_y,
            )
            pdf.setLineWidth(0.7)
            pdf.drawPath(path, stroke=1, fill=0)

        for part_index, source, target in slur_pairs:
            if source.measure_index not in measure_layout:
                continue
            source_x, source_y, source_mapped, source_width = event_geometry[id(source)]
            target_geometry = event_geometry[id(target)]
            target_x = target_geometry[0]
            target_width = target_geometry[3]
            start_x = source_x + source_width / 2
            end_x = target_x + target_width / 2
            lane_events = [
                event
                for event in score.parts[part_index].events
                if event.staff_number == source.staff_number
                and event.voice_id == source.voice_id
                and (source.measure_index, source.onset)
                <= (event.measure_index, event.onset)
                <= (target.measure_index, target.onset)
            ]
            high_marks = [
                10.0 + (octave - 1) * 3.5 + 1.2
                for event in lane_events
                for _degree, octave in _mapped_pitches(
                    event, notation=notation, context=contexts.get(event.measure_index)
                )
                if octave > 0
            ]
            slur_y = source_y + max([14.0, *(mark + 4.0 for mark in high_marks)])
            path = pdf.beginPath()
            path.moveTo(start_x, slur_y)
            path.curveTo(
                start_x + (end_x - start_x) / 3.0,
                slur_y + 3.0,
                start_x + 2.0 * (end_x - start_x) / 3.0,
                slur_y + 3.0,
                end_x,
                slur_y,
            )
            pdf.setLineWidth(0.7)
            pdf.drawPath(path, stroke=1, fill=0)

        if page_index < len(measure_groups) - 1:
            pdf.showPage()

    pdf.save()
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(
            f"PDF renderer did not produce the expected output: {output}"
        )
    return output
