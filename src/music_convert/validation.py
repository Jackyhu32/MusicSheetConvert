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


def _measure_positions(model: ScoreModel):
    measures = sorted(model.measures, key=lambda measure: measure.index)
    measure_by_index = {measure.index: measure for measure in measures}
    measure_starts: dict[int, Fraction] = {}
    absolute_start = Fraction(0)
    for measure in measures:
        measure_starts[measure.index] = absolute_start
        absolute_start += measure.duration
    return measure_by_index, measure_starts


def _validate_timeline(
    model: ScoreModel, measure_by_index: dict[int, object]
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for part in model.parts:
        grouped: dict[tuple[int, str, str], list[ScoreEvent]] = defaultdict(list)
        for item in part.events:
            grouped[(item.measure_index, item.staff_number, item.voice_id)].append(item)

        for (measure_index, _staff, _voice), events in sorted(grouped.items()):
            measure = measure_by_index.get(measure_index)
            if measure is None:
                item = events[0]
                issues.append(
                    ValidationIssue(
                        "unknown_measure",
                        part.id,
                        str(measure_index),
                        f"Event references undeclared measure index {measure_index}.",
                        item.source_location,
                    )
                )
                continue

            cursor = Fraction(0)
            ordered_events = sorted(events, key=lambda value: (value.onset, value.duration))
            for item in ordered_events:
                if item.grace and item.duration == 0:
                    continue
                if item.duration <= 0:
                    issues.append(
                        ValidationIssue(
                            "invalid_duration",
                            part.id,
                            measure.number,
                            "Event duration must be positive.",
                            item.source_location,
                        )
                    )
                if item.onset > cursor:
                    issues.append(
                        ValidationIssue(
                            "measure_gap",
                            part.id,
                            measure.number,
                            f"Voice has an uncovered interval from {cursor} to {item.onset}.",
                            item.source_location,
                        )
                    )
                elif item.onset < cursor:
                    issues.append(
                        ValidationIssue(
                            "measure_overlap",
                            part.id,
                            measure.number,
                            f"Event at {item.onset} overlaps the preceding event ending at {cursor}.",
                            item.source_location,
                        )
                    )
                end = item.onset + item.duration
                if end > measure.duration:
                    issues.append(
                        ValidationIssue(
                            "measure_overflow",
                            part.id,
                            measure.number,
                            f"Event ends at {end}, beyond declared measure duration {measure.duration}.",
                            item.source_location,
                        )
                    )
                cursor = max(cursor, end)
            if cursor < measure.duration:
                issues.append(
                    ValidationIssue(
                        "measure_gap",
                        part.id,
                        measure.number,
                        f"Voice ends at {cursor}, before declared measure duration {measure.duration}.",
                        ordered_events[-1].source_location,
                    )
                )
    return issues


def _validate_pitch_data(
    model: ScoreModel,
    measure_by_index: dict[int, object],
    measure_starts: dict[int, Fraction],
) -> tuple[list[ValidationIssue], dict[tuple[str, str, str], list[tuple[Fraction, ScoreEvent]]]]:
    issues: list[ValidationIssue] = []
    tie_streams: dict[tuple[str, str, str], list[tuple[Fraction, ScoreEvent]]] = defaultdict(list)
    for part in model.parts:
        for item in part.events:
            if item.kind == "rest":
                continue
            measure = measure_by_index.get(item.measure_index)
            measure_number = measure.number if measure else str(item.measure_index)
            try:
                sounding = item.effective_sounding_pitches
            except ValueError:
                issues.append(
                    ValidationIssue(
                        "missing_sounding_pitch",
                        part.id,
                        measure_number,
                        "Pitched event has no explicit sounding pitches.",
                        item.source_location,
                    )
                )
                sounding = ()
            if len(sounding) != len(item.pitches):
                issues.append(
                    ValidationIssue(
                        "sounding_pitch_count_mismatch",
                        part.id,
                        measure_number,
                        "Written and sounding pitch counts must match one-to-one.",
                        item.source_location,
                    )
                )
            if not sounding or any(not _valid_pitch(pitch) for pitch in sounding):
                if sounding:
                    issues.append(
                        ValidationIssue(
                            "invalid_sounding_pitch",
                            part.id,
                            measure_number,
                            "Every sounding pitch must have a valid step, alteration, and octave.",
                            item.source_location,
                        )
                    )
                continue
            if item.measure_index not in measure_starts:
                continue
            tie_streams[(part.id, item.staff_number, item.voice_id)].append(
                (measure_starts[item.measure_index] + item.onset, item)
            )
    return issues, tie_streams


def _validate_ties(
    tie_streams: dict[tuple[str, str, str], list[tuple[Fraction, ScoreEvent]]],
    measure_by_index: dict[int, object],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
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
                measure_number = measure_by_index[item.measure_index].number
                if len(states) != count:
                    issues.append(
                        ValidationIssue(
                            "tie_state_count_mismatch",
                            part_id,
                            measure_number,
                            "Tie state count must match the event pitch count.",
                            item.source_location,
                        )
                    )
                for index, pitch in enumerate(item.effective_sounding_pitches[:count]):
                    state = states[index] if index < len(states) else "none"
                    if state not in {"none", "start", "stop", "continue"}:
                        issues.append(
                            ValidationIssue(
                                "invalid_tie_state",
                                part_id,
                                measure_number,
                                f"Unsupported tie state {state!r}.",
                                item.source_location,
                            )
                        )
                        continue
                    if state != "none":
                        transitions.append((_pitch_number(pitch), state, item.duration, item))

            used: set[int] = set()
            for pitch_number, entries in list(pending.items()):
                for expected_onset, start_item, pending_state in list(entries):
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
                        entries.remove((expected_onset, start_item, pending_state))
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
                        issues.append(
                            ValidationIssue(
                                code,
                                part_id,
                                measure_by_index[target_item.measure_index].number,
                                "Tie does not continue at the next contiguous onset with the same sounding pitch."
                                if code == "tie_discontinuity"
                                else "Tied notes have different sounding pitches.",
                                target_item.source_location,
                            )
                        )
                        entries.remove((expected_onset, start_item, pending_state))
                if not entries:
                    pending.pop(pitch_number, None)

            for index, (pitch_number, state, duration, item) in enumerate(transitions):
                if index in used:
                    if state == "continue":
                        pending[pitch_number].append((onset + duration, item, "continue"))
                    continue
                measure_number = measure_by_index[item.measure_index].number
                if state in {"stop", "continue"}:
                    issues.append(
                        ValidationIssue(
                            "tie_orphan_stop",
                            part_id,
                            measure_number,
                            "Tie stop has no matching contiguous start in this staff and voice.",
                            item.source_location,
                        )
                    )
                if state in {"start", "continue"}:
                    pending[pitch_number].append((onset + duration, item, state))

        for entries in pending.values():
            for _expected, start_item, _state in entries:
                issues.append(
                    ValidationIssue(
                        "tie_unmatched_start",
                        part_id,
                        measure_by_index[start_item.measure_index].number,
                        "Tie start has no matching stop.",
                        start_item.source_location,
                    )
                )
    return issues


def _validate_review_issues(model: ScoreModel) -> list[ValidationIssue]:
    issues = []
    for review in model.review_issues:
        location = review.location
        issues.append(
            ValidationIssue(
                "review_required",
                "",
                location.measure_number if location and location.measure_number else "",
                f"Unresolved review issue {review.code}: {review.message}",
                location,
            )
        )
    if model.requires_review and not model.review_issues:
        issues.append(ValidationIssue("review_required", "", "", "Score is marked as requiring review."))
    return issues


def validate_score(model: ScoreModel) -> list[ValidationIssue]:
    """Return stable, source-located issues found in the score model."""
    measure_by_index, measure_starts = _measure_positions(model)
    pitch_issues, tie_streams = _validate_pitch_data(model, measure_by_index, measure_starts)
    return (
        _validate_timeline(model, measure_by_index)
        + pitch_issues
        + _validate_ties(tie_streams, measure_by_index)
        + _validate_review_issues(model)
    )
