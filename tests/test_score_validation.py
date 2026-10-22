import unittest
from fractions import Fraction

from src.music_convert.model import (
    MeasureContext,
    Pitch,
    ReviewIssue,
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
    kind="note",
    pitches=None,
    sounding_pitches=None,
    ties=(),
    voice="1",
    staff="1",
    location=None,
):
    if pitches is None:
        pitches = () if kind == "rest" else (Pitch("C", 0, 4),)
    if sounding_pitches is None:
        if kind != "rest":
            raise AssertionError("pitched fixtures must explicitly set sounding_pitches")
        sounding_pitches = ()
    return ScoreEvent(
        "P",
        measure,
        voice,
        Fraction(onset),
        Fraction(duration),
        kind,
        pitches,
        sounding_pitches,
        ties,
        staff,
        source_location=location,
    )


def model(events, durations=(4,), *, pickup=False, review_issues=()):
    measures = [
        MeasureContext(
            index,
            str(index + 1),
            Fraction(duration),
            0,
            "major",
            4,
            4,
            pickup=pickup and index == 0,
        )
        for index, duration in enumerate(durations)
    ]
    return ScoreModel(
        "",
        [ScorePart("P", "Part", events=events)],
        measures,
        review_issues=list(review_issues),
    )


class ScoreValidationTests(unittest.TestCase):
    def codes(self, score):
        return [issue.code for issue in validate_score(score)]

    def test_exact_tuplet_chord_and_rest_cover_measure_without_summing_chord_tones(self):
        score = model(
            [
                event(0, 0, 1, sounding_pitches=(Pitch("C", 0, 4),)),
                event(0, 1, Fraction(1, 3), sounding_pitches=(Pitch("C", 0, 4),)),
                event(0, Fraction(4, 3), Fraction(1, 3), sounding_pitches=(Pitch("C", 0, 4),)),
                event(0, Fraction(5, 3), Fraction(1, 3), sounding_pitches=(Pitch("C", 0, 4),)),
                event(
                    0,
                    2,
                    1,
                    "chord",
                    (Pitch("C", 0, 4), Pitch("E", 0, 4), Pitch("G", 0, 4)),
                    sounding_pitches=(Pitch("C", 0, 4), Pitch("E", 0, 4), Pitch("G", 0, 4)),
                    ties=("none", "none", "none"),
                ),
                event(0, 3, 1, "rest"),
            ]
        )
        self.assertEqual([], validate_score(score))

    def test_pickup_is_checked_against_declared_actual_duration(self):
        score = model([event(0, 0, 1, sounding_pitches=(Pitch("C", 0, 4),))], durations=(1,), pickup=True)
        self.assertEqual([], validate_score(score))

    def test_measure_gap_overlap_and_overflow_have_stable_codes(self):
        cases = (
            (model([event(0, 0, 1, sounding_pitches=(Pitch("C", 0, 4),)), event(0, 2, 2, sounding_pitches=(Pitch("C", 0, 4),))]), "measure_gap"),
            (model([event(0, 0, 2, sounding_pitches=(Pitch("C", 0, 4),)), event(0, 1, 3, sounding_pitches=(Pitch("C", 0, 4),))]), "measure_overlap"),
            (model([event(0, 0, 5, sounding_pitches=(Pitch("C", 0, 4),))]), "measure_overflow"),
        )
        for score, code in cases:
            with self.subTest(code=code):
                self.assertIn(code, self.codes(score))

    def test_distinct_voices_do_not_accumulate_into_each_other(self):
        score = model(
            [
                event(0, 0, 4, sounding_pitches=(Pitch("C", 0, 4),), voice="1"),
                event(0, 0, 4, sounding_pitches=(Pitch("C", 0, 4),), voice="2"),
            ]
        )
        self.assertEqual([], validate_score(score))

    def test_cross_measure_tie_uses_absolute_onset_and_sounding_pitch(self):
        score = model(
            [
                event(0, 0, 3, "rest"),
                event(
                    0,
                    3,
                    1,
                    pitches=(Pitch("D", -1, 4),),
                    sounding_pitches=(Pitch("C", 1, 4),),
                    ties=("start",),
                ),
                event(
                    1,
                    0,
                    1,
                    pitches=(Pitch("C", 1, 4),),
                    sounding_pitches=(Pitch("D", -1, 4),),
                    ties=("stop",),
                ),
                event(1, 1, 3, "rest"),
            ],
            durations=(4, 4),
        )
        self.assertEqual([], validate_score(score))

    def test_ties_are_isolated_by_staff_and_voice(self):
        for changed in ("staff", "voice"):
            with self.subTest(changed=changed):
                stop_kwargs = {"staff": "2"} if changed == "staff" else {"voice": "2"}
                score = model(
                    [
                        event(0, 0, 3, "rest"),
                        event(0, 3, 1, ties=("start",), sounding_pitches=(Pitch("C", 0, 4),)),
                        event(1, 0, 1, ties=("stop",), sounding_pitches=(Pitch("C", 0, 4),), **stop_kwargs),
                        event(1, 1, 3, "rest", **stop_kwargs),
                    ],
                    durations=(4, 4),
                )
                self.assertIn("tie_unmatched_start", self.codes(score))
                self.assertIn("tie_orphan_stop", self.codes(score))

    def test_chord_tie_states_are_validated_per_pitch(self):
        pitches = (Pitch("C", 0, 4), Pitch("E", 0, 4))
        score = model(
            [
                event(0, 0, 3, "rest"),
                event(0, 3, 1, "chord", pitches, sounding_pitches=pitches, ties=("start", "none")),
                event(1, 0, 1, "chord", pitches, sounding_pitches=pitches, ties=("stop", "none")),
                event(1, 1, 3, "rest"),
            ],
            durations=(4, 4),
        )
        self.assertEqual([], validate_score(score))

    def test_wrong_pitch_orphan_stop_unclosed_start_and_discontinuous_tie_report(self):
        with self.subTest(case="wrong pitch"):
            score = model(
                [
                    event(0, 0, 3, "rest"),
                    event(0, 3, 1, ties=("start",), sounding_pitches=(Pitch("C", 0, 4),)),
                    event(1, 0, 1, pitches=(Pitch("D", 0, 4),), sounding_pitches=(Pitch("D", 0, 4),), ties=("stop",)),
                    event(1, 1, 3, "rest"),
                ],
                durations=(4, 4),
            )
            issue = next(i for i in validate_score(score) if i.code == "tie_pitch_mismatch")
            self.assertEqual(("P", "2"), (issue.part_id, issue.measure_number))

        cases = (
            ([event(0, 0, 1, ties=("stop",), sounding_pitches=(Pitch("C", 0, 4),))], "tie_orphan_stop"),
            ([event(0, 0, 1, ties=("start",), sounding_pitches=(Pitch("C", 0, 4),)), event(0, 1, 3, "rest")],
             "tie_unmatched_start"),
            (
                [
                    event(0, 0, 1, ties=("start",), sounding_pitches=(Pitch("C", 0, 4),)),
                    event(0, 1, 1, "rest"),
                    event(0, 2, 1, ties=("stop",), sounding_pitches=(Pitch("C", 0, 4),)),
                    event(0, 3, 1, "rest"),
                ],
                "tie_discontinuity",
            ),
        )
        for events, code in cases:
            with self.subTest(code=code):
                self.assertIn(code, self.codes(model(events)))

    def test_missing_or_non_one_to_one_sounding_pitches_are_issues(self):
        source = SourceLocation(page=2, system=3, measure_number="1")
        missing = event(
            0,
            0,
            4,
            pitches=(Pitch("C", 0, 4),),
            sounding_pitches=(),
            location=source,
        )
        issue = next(
            i for i in validate_score(model([missing])) if i.code == "missing_sounding_pitch"
        )
        self.assertEqual(source, issue.location)

        mismatch = event(
            0,
            0,
            4,
            "chord",
            (Pitch("C", 0, 4), Pitch("E", 0, 4)),
            sounding_pitches=(Pitch("C", 0, 4),),
        )
        self.assertIn("sounding_pitch_count_mismatch", self.codes(model([mismatch])))

    def test_unresolved_review_issue_is_preserved_as_locatable_validation_issue(self):
        location = SourceLocation(page=1, system=2, measure_number="7")
        score = model(
            [event(0, 0, 4, sounding_pitches=(Pitch("C", 0, 4),))],
            review_issues=(ReviewIssue("uncertain_pitch", "Confirm pitch", location),),
        )
        issue = next(i for i in validate_score(score) if i.code == "review_required")
        self.assertEqual(("7", location), (issue.measure_number, issue.location))
        self.assertIn("uncertain_pitch", issue.message)


if __name__ == "__main__":
    unittest.main()
