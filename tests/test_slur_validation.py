import unittest
from fractions import Fraction

from src.music_convert.model import (
    MeasureContext,
    Pitch,
    ScoreEvent,
    ScoreModel,
    ScorePart,
    SourceLocation,
)
from src.music_convert.validation import validate_score


def event(
    measure,
    onset,
    duration,
    *,
    state=None,
    number="1",
    part_id="P",
    voice="1",
    staff="1",
    location=None,
    rest=False,
):
    kind = "rest" if rest else "note"
    pitch = () if rest else (Pitch("C", 0, 4),)
    slurs = ((state, number),) if state else ()
    return ScoreEvent(
        part_id=part_id,
        measure_index=measure,
        voice_id=voice,
        onset=Fraction(onset),
        duration=Fraction(duration),
        kind=kind,
        pitches=pitch,
        sounding_pitches=pitch,
        staff_number=staff,
        source_location=location,
        slurs=slurs,
    )


def score(events, *, durations=(4,)):
    return ScoreModel(
        title="",
        parts=[ScorePart("P", "Part", events=events)],
        measures=[
            MeasureContext(i, str(i + 1), Fraction(length), 0, "major", 4, 4)
            for i, length in enumerate(durations)
        ],
    )


class SlurValidationTests(unittest.TestCase):
    def test_unmatched_start_has_stable_code_and_source_location(self):
        location = SourceLocation(page=3, system=2, measure_number="7")
        issues = validate_score(
            score(
                [
                    event(0, 0, 2, state="start", number="2", location=location),
                    event(0, 2, 2, rest=True),
                ]
            )
        )
        self.assertEqual(
            [("slur_unmatched_start", "P", "1", location)],
            [(i.code, i.part_id, i.measure_number, i.location) for i in issues],
        )

    def test_orphan_stop_and_continue_have_stable_codes_and_locations(self):
        for state, code in (
            ("stop", "slur_orphan_stop"),
            ("continue", "slur_orphan_continue"),
        ):
            with self.subTest(state=state):
                location = SourceLocation(page=2, system=1, measure_number="4")
                issues = validate_score(
                    score(
                        [
                            event(0, 0, 2, state=state, location=location),
                            event(0, 2, 2, rest=True),
                        ]
                    )
                )
                self.assertEqual([code], [issue.code for issue in issues])
                self.assertEqual(location, issues[0].location)

    def test_start_continue_stop_chain_across_pages_is_valid(self):
        locations = (
            SourceLocation(page=1, system=1, measure_number="1"),
            SourceLocation(page=2, system=1, measure_number="2"),
            SourceLocation(page=2, system=1, measure_number="2"),
        )
        issues = validate_score(
            score(
                [
                    event(0, 0, 2, state="start", number="3", location=locations[0]),
                    event(0, 2, 2, rest=True),
                    event(1, 0, 2, state="continue", number="3", location=locations[1]),
                    event(1, 2, 2, state="stop", number="3", location=locations[2]),
                ],
                durations=(4, 4),
            )
        )
        self.assertEqual([], issues)

    def test_pairing_is_scoped_by_part_staff_voice_and_number(self):
        start_location = SourceLocation(page=1, system=1, measure_number="1")
        stop_location = SourceLocation(page=2, system=1, measure_number="1")
        model = score(
            [
                event(0, 0, 2, state="start", number="1", location=start_location),
                event(0, 2, 2, rest=True),
                event(
                    0,
                    0,
                    2,
                    state="stop",
                    number="2",
                    staff="2",
                    voice="2",
                    location=stop_location,
                ),
                event(0, 2, 2, rest=True, staff="2", voice="2"),
            ]
        )
        other_part_stop = event(
            0,
            0,
            4,
            state="stop",
            number="2",
            part_id="Q",
            location=stop_location,
        )
        model.parts.append(ScorePart("Q", "Other Part", events=[other_part_stop]))

        issues = validate_score(model)
        unmatched = next(i for i in issues if i.code == "slur_unmatched_start")
        orphan = next(
            i for i in issues if i.code == "slur_orphan_stop" and i.part_id == "Q"
        )
        self.assertEqual("P", unmatched.part_id)
        self.assertEqual("Q", orphan.part_id)


if __name__ == "__main__":
    unittest.main()
