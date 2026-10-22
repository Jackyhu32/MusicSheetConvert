from dataclasses import FrozenInstanceError
from fractions import Fraction
import unittest

from src.music_convert.model import (
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


class ScoreModelTests(unittest.TestCase):
    def test_value_objects_keep_their_declared_fields_and_defaults(self):
        pitch = Pitch("F", 1, 4)
        lyric = Lyric("星")
        location = SourceLocation()
        issue = ReviewIssue("uncertain", "Check this note")
        staff = StaffContext("1")

        self.assertEqual(("F", 1, 4), (pitch.step, pitch.alter, pitch.octave))
        self.assertEqual(("星", "1", "single", False),
                         (lyric.text, lyric.number, lyric.syllabic, lyric.extend))
        self.assertEqual((None, None, None),
                         (location.page, location.system, location.measure_number))
        self.assertEqual((None, (), None),
                         (issue.location, issue.candidates, issue.confidence))
        self.assertEqual(("1", None, None, 0),
                         (staff.number, staff.clef_sign, staff.clef_line,
                          staff.clef_octave_change))

        with self.assertRaises(FrozenInstanceError):
            pitch.step = "G"
        with self.assertRaises(FrozenInstanceError):
            lyric.text = "月"

    def test_event_preserves_fraction_timing_pitch_lyrics_and_per_pitch_ties(self):
        pitches = (Pitch("F", 1, 4), Pitch("A", 0, 4))
        lyrics = (Lyric("星", number="2", syllabic="begin", extend=True),)
        event = ScoreEvent(
            part_id="S",
            measure_index=0,
            voice_id="1",
            onset=Fraction(1, 2),
            duration=Fraction(3, 2),
            kind="chord",
            pitches=pitches,
            sounding_pitches=(Pitch("F", 1, 4), Pitch("A", 0, 4)),
            pitch_ties=("start", "none"),
            staff_number="2",
            lyrics=lyrics,
            source_location=SourceLocation(page=1, system=2, measure_number="3"),
        )

        self.assertEqual(Fraction(1, 2), event.onset)
        self.assertEqual(Fraction(3, 2), event.duration)
        self.assertEqual(pitches, event.pitches)
        self.assertEqual(("start", "none"), event.pitch_ties)
        self.assertEqual(lyrics, event.lyrics)
        self.assertEqual("3", event.source_location.measure_number)

    def test_event_keeps_written_and_sounding_pitches_independently(self):
        written_pitch = Pitch("C", 0, 4)
        sounding_pitch = Pitch("B", -1, 3)
        event = ScoreEvent(
            part_id="BbClarinet",
            measure_index=0,
            voice_id="1",
            onset=Fraction(0),
            duration=Fraction(1),
            kind="note",
            pitches=(written_pitch,),
            sounding_pitches=(sounding_pitch,),
        )

        self.assertEqual((written_pitch,), event.written_pitches)
        self.assertEqual((written_pitch,), event.pitches)
        self.assertEqual((sounding_pitch,), event.sounding_pitches)
        self.assertEqual((sounding_pitch,), event.effective_sounding_pitches)
        self.assertNotEqual(event.written_pitches, event.sounding_pitches)

    def test_effective_sounding_pitches_fall_back_to_written_pitches_or_empty_for_rest(self):
        written_pitch = Pitch("G", 0, 4)
        note = ScoreEvent(
            part_id="S",
            measure_index=0,
            voice_id="1",
            onset=Fraction(0),
            duration=Fraction(1),
            kind="note",
            pitches=(written_pitch,),
        )
        rest = ScoreEvent(
            part_id="S",
            measure_index=0,
            voice_id="1",
            onset=Fraction(1),
            duration=Fraction(1),
            kind="rest",
            pitches=(written_pitch,),
        )

        self.assertEqual((written_pitch,), note.effective_sounding_pitches)
        self.assertEqual((), rest.effective_sounding_pitches)

    def test_timing_contexts_and_model_constructors_keep_exact_values(self):
        direction = ScoreDirection(0, Fraction(1, 3), "dynamic", "p")
        measure = MeasureContext(0, "1", Fraction(7, 2), 2, "major", 7, 4,
                                 pickup=True)
        part = ScorePart("S", "Soprano", transpose_semitones=-2)
        model = ScoreModel("Title", [part], [measure], tempo_bpm=96.5,
                           directions=[direction], source_musicxml=b"<score/>",
                           requires_review=True,
                           review_issues=[ReviewIssue("uncertain", "Review")])

        self.assertEqual(Fraction(1, 3), direction.onset)
        self.assertEqual(Fraction(7, 2), measure.duration)
        self.assertTrue(measure.pickup)
        self.assertEqual(-2, part.transpose_semitones)
        self.assertEqual(96.5, model.tempo_bpm)
        self.assertEqual([direction], model.directions)
        self.assertEqual(b"<score/>", model.source_musicxml)
        self.assertTrue(model.requires_review)
        self.assertEqual(1, len(model.review_issues))

    def test_mutable_container_defaults_are_independent(self):
        first_part = ScorePart("S", "Soprano")
        second_part = ScorePart("A", "Alto")
        first_model = ScoreModel("", [], [])
        second_model = ScoreModel("", [], [])

        first_part.staves.append(StaffContext("1"))
        first_part.events.append(
            ScoreEvent("S", 0, "1", Fraction(0), Fraction(1), "rest")
        )
        first_model.directions.append(ScoreDirection(0, Fraction(0), "tempo", "90"))
        first_model.review_issues.append(ReviewIssue("uncertain", "Review"))

        self.assertEqual([], second_part.staves)
        self.assertEqual([], second_part.events)
        self.assertEqual([], second_model.directions)
        self.assertEqual([], second_model.review_issues)


if __name__ == "__main__":
    unittest.main()
