"""Semantic validation for score event timing and ties."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from .model import Pitch, ScoreEvent, ScoreModel, SourceLocation


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    part_id: str
    measure_number: str
    message: str
    location: SourceLocation | None = None


def _pitch_number(pitch: Pitch) -> int:
    natural = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return 12 * pitch.octave + natural[pitch.step] + pitch.alter


def _valid_pitch(pitch: object) -> bool:
    return (
        isinstance(pitch, Pitch)
        and pitch.step in {"A", "B", "C", "D", "E", "F", "G"}
        and isinstance(pitch.alter, int)
        and isinstance(pitch.octave, int)
    )


def validate_score(model: ScoreModel) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(
        code: str,
        part_id: str,
        measure_number: str,
        message: str,
        location: SourceLocation | None = None,
    ) -> None:
        issues.append(ValidationIssue(code, part_id, measure_number, message, location))

    measures = sorted(model.measures, key=lambda measure: measure.index)
    measure_by_index = {measure.index: measure for measure in measures}
    measure_starts: dict[int, Fraction] = {}
    absolute_start = Fraction(0)
    for measure in measures:
        measure_starts[measure.index] = absolute_start
        absolute_start += measure.duration

    # Validate each represented voice independently; absent voices imply no coverage.
    for part in model.parts:
        grouped: dict[tuple[int, str, str], list[ScoreEvent]] = defaultdict(list)
        for item in part.events:
            grouped[(item.measure_index, item.staff_number, item.voice_id)].append(item)

        for (measure_index, _staff, _voice), events in sorted(grouped.items()):
            measure = measure_by_index.get(measure_index)
            if measure is None:
                item = events[0]
                add(
                    "unknown_measure",
                    part.id,
                    str(measure_index),
                    f"Event references undeclared measure index {measure_index}.",
                    item.source_location,
                )
                continue

            cursor = Fraction(0)
            for item in sorted(events, key=lambda value: (value.onset, value.duration)):
                number = measure.number
                if item.duration <= 0:
                    add(
                        "invalid_duration",
                        part.id,
                        number,
                        "Event duration must be positive.",
                        item.source_location,
                    )
                if item.onset > cursor:
                    add(
                        "measure_gap",
                        part.id,
                        number,
                        f"Voice has an uncovered interval from {cursor} to {item.onset}.",
                        item.source_location,
                    )
                elif item.onset < cursor:
                    add(
                        "measure_overlap",
                        part.id,
                        number,
                        f"Event at {item.onset} overlaps the preceding event ending at {cursor}.",
                        item.source_location,
                    )
                end = item.onset + item.duration
                if end > measure.duration:
                    add(
                        "measure_overflow",
                        part.id,
                        number,
                        f"Event ends at {end}, beyond declared measure duration {measure.duration}.",
                        item.source_location,
                    )
                cursor = max(cursor, end)
            if cursor < measure.duration:
                add(
                    "measure_gap",
                    part.id,
                    measure.number,
                    f"Voice ends at {cursor}, before declared measure duration {measure.duration}.",
                    events[-1].source_location,
                )

    # Validate note/chord pitch cardinality and each pitch-level tie transition.
    tie_streams: dict[tuple[str, str, str], list[tuple[Fraction, ScoreEvent]]] = defaultdict(list)
    for part in model.parts:
        for item in part.events:
            if item.kind == "rest":
                continue
            number = measure_by_index.get(item.measure_index)
            measure_number = number.number if number else str(item.measure_index)
            try:
                sounding = item.effective_sounding_pitches
            except ValueError:
                add(
                    "missing_sounding_pitch",
                    part.id,
                    measure_number,
                    "Pitched event has no explicit sounding pitches.",
                    item.source_location,
                )
                sounding = ()
            if len(sounding) != len(item.pitches):
                add(
                    "sounding_pitch_count_mismatch",
                    part.id,
                    measure_number,
                    "Written and sounding pitch counts must match one-to-one.",
                    item.source_location,
                )
            if not sounding or any(not _valid_pitch(pitch) for pitch in sounding):
                if sounding:
                    add(
                        "invalid_sounding_pitch",
                        part.id,
                        measure_number,
                        "Every sounding pitch must have a valid step, alteration, and octave.",
                        item.source_location,
                    )
                continue
            if item.measure_index not in measure_starts:
                continue
            stream_key = (part.id, item.staff_number, item.voice_id)
            tie_streams[stream_key].append(
                (measure_starts[item.measure_index] + item.onset, item)
            )

    for (part_id, _staff, _voice), timed_events in sorted(tie_streams.items()):
        pending: dict[int, list[tuple[Fraction, ScoreEvent, str]]] = defaultdict(list)
        by_onset: dict[Fraction, list[ScoreEvent]] = defaultdict(list)
        for onset, item in timed_events:
            by_onset[onset].append(item)

        for onset in sorted(by_onset):
            current_events = by_onset[onset]
            transitions: list[tuple[int, str, Fraction, ScoreEvent]] = []
            for item in current_events:
                count = len(item.pitches)
                states = item.pitch_ties or ("none",) * count
                if len(states) != count:
                    add(
                        "tie_state_count_mismatch",
                        part_id,
                        measure_by_index[item.measure_index].number,
                        "Tie state count must match the event pitch count.",
                        item.source_location,
                    )
                sounding = item.effective_sounding_pitches
                for index, pitch in enumerate(sounding[:count]):
                    state = states[index] if index < len(states) else "none"
                    if state not in {"none", "start", "stop", "continue"}:
                        add(
                            "invalid_tie_state",
                            part_id,
                            measure_by_index[item.measure_index].number,
                            f"Unsupported tie state {state!r}.",
                            item.source_location,
                        )
                        continue
                    if state != "none":
                        transitions.append(
                            (_pitch_number(pitch), state, item.duration, item)
                        )

            used: set[int] = set()
            for pitch_number, entries in list(pending.items()):
                for expected_onset, start_item, _state in list(entries):
                    transition_index = next(
                        (
                            index
                            for index, (target, state, _duration, _item) in enumerate(transitions)
                            if index not in used
                            and target == pitch_number
                            and state in {"stop", "continue"}
                        ),
                        None,
                    )
                    if expected_onset == onset and transition_index is not None:
                        used.add(transition_index)
                        entries.remove((expected_onset, start_item, _state))
                    elif expected_onset <= onset:
                        code = "tie_discontinuity"
                        if transition_index is not None:
                            used.add(transition_index)
                        else:
                            mismatched_stop = next(
                                (
                                    index
                                    for index, (_target, state, _duration, _item) in enumerate(transitions)
                                    if index not in used and state in {"stop", "continue"}
                                ),
                                None,
                            )
                            if expected_onset == onset and mismatched_stop is not None:
                                used.add(mismatched_stop)
                                code = "tie_pitch_mismatch"
                        target_item = current_events[0]
                        add(
                            code,
                            part_id,
                            measure_by_index[target_item.measure_index].number,
                            "Tie does not continue at the next contiguous onset with the same sounding pitch."
                            if code == "tie_discontinuity"
                            else "Tied notes have different sounding pitches.",
                            target_item.source_location,
                        )
                        entries.remove((expected_onset, start_item, _state))
                if not entries:
                    pending.pop(pitch_number, None)

            for index, (pitch_number, state, duration, item) in enumerate(transitions):
                if index in used:
                    if state == "continue":
                        pending[pitch_number].append(
                            (onset + duration, item, "continue")
                        )
                    continue
                number = measure_by_index[item.measure_index].number
                if state in {"stop", "continue"}:
                    add(
                        "tie_orphan_stop",
                        part_id,
                        number,
                        "Tie stop has no matching contiguous start in this staff and voice.",
                        item.source_location,
                    )
                if state in {"start", "continue"}:
                    pending[pitch_number].append((onset + duration, item, state))

        for entries in pending.values():
            for _expected, start_item, _state in entries:
                add(
                    "tie_unmatched_start",
                    part_id,
                    measure_by_index[start_item.measure_index].number,
                    "Tie start has no matching stop.",
                    start_item.source_location,
                )

    for review in model.review_issues:
        location = review.location
        add(
            "review_required",
            "",
            location.measure_number if location and location.measure_number else "",
            f"Unresolved review issue {review.code}: {review.message}",
            location,
        )
    if model.requires_review and not model.review_issues:
        add("review_required", "", "", "Score is marked as requiring review.")

    return issues
