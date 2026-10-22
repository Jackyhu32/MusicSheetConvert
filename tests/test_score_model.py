import unittest
from dataclasses import FrozenInstanceError
from fractions import Fraction

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
        self.assertEqual(
            ("星", "1", "single", False),
            (lyric.text, lyric.number, lyric.syllabic, lyric.extend),
        )
        self.assertEqual(
            (None, None, None),
            (location.page, location.system, location.measure_number),
        )
        self.assertEqual(
            (None, (), None), (issue.location, issue.candidates, issue.confidence)
        )
        self.assertEqual(
            ("1", None, None, 0),
            (staff.number, staff.clef_sign, staff.clef_line, staff.clef_octave_change),
        )

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

    def test_effective_sounding_pitches_requires_explicit_pitch_for_pitched_events(
        self,
    ):
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
        chord = ScoreEvent(
            part_id="S",
            measure_index=0,
            voice_id="1",
            onset=Fraction(1),
            duration=Fraction(1),
            kind="chord",
            pitches=(written_pitch, Pitch("B", 0, 4)),
        )
        rest = ScoreEvent(
            part_id="S",
            measure_index=0,
            voice_id="1",
            onset=Fraction(2),
            duration=Fraction(1),
            kind="rest",
            pitches=(written_pitch,),
        )

        message = "sounding pitches must be explicitly provided before conversion"
        with self.assertRaisesRegex(ValueError, message):
            _ = note.effective_sounding_pitches
        with self.assertRaisesRegex(ValueError, message):
            _ = chord.effective_sounding_pitches
        self.assertEqual((), rest.effective_sounding_pitches)

    def test_timing_contexts_and_model_constructors_keep_exact_values(self):
        direction = ScoreDirection(0, Fraction(1, 3), "dynamic", "p")
        measure = MeasureContext(0, "1", Fraction(7, 2), 2, "major", 7, 4, pickup=True)
        part = ScorePart("S", "Soprano", transpose_semitones=-2)
        model = ScoreModel(
            "Title",
            [part],
            [measure],
            tempo_bpm=96.5,
            directions=[direction],
            source_musicxml=b"<score/>",
            requires_review=True,
            review_issues=[ReviewIssue("uncertain", "Review")],
        )

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


class MusicXmlParsingTests(unittest.TestCase):
    def fixture(self, name):
        from pathlib import Path

        return Path(__file__).parent / "fixtures" / name

    def test_import_preserves_satbb_parts_and_original_bytes(self):
        from src.music_convert.musicxml_io import load_musicxml

        path = self.fixture("satbb-two-measures.musicxml")
        source_bytes = path.read_bytes()
        model = load_musicxml(path)

        self.assertEqual(source_bytes, model.source_musicxml)
        self.assertEqual("SATBB Exact Timing", model.title)
        self.assertEqual(
            ["P-S", "P-A", "P-T", "P-BR", "P-B"],
            [part.id for part in model.parts],
        )
        self.assertEqual(
            ["Soprano", "Alto", "Tenor", "Baritone", "Bass"],
            [part.name for part in model.parts],
        )
        self.assertEqual(5, len({part.id for part in model.parts}))
        self.assertEqual(0, model.parts[0].transpose_semitones)
        self.assertEqual(-12, model.parts[2].transpose_semitones)
        tenor_note = model.parts[2].events[0]
        self.assertEqual((Pitch("C", 0, 4),), tenor_note.pitches)
        self.assertEqual((Pitch("C", 0, 3),), tenor_note.sounding_pitches)
        self.assertEqual("G", model.parts[0].staves[0].clef_sign)
        self.assertEqual(2, model.parts[0].staves[0].clef_line)
        self.assertEqual(92, model.tempo_bpm)
        self.assertTrue(any(d.value == "dolce" for d in model.directions))
        self.assertTrue(any(d.value == "p" for d in model.directions))

    def test_import_preserves_exact_event_context_and_music_notation(self):
        from src.music_convert.musicxml_io import load_musicxml

        model = load_musicxml(self.fixture("satbb-two-measures.musicxml"))
        soprano = model.parts[0].events
        dotted = next(
            event for event in soprano if event.pitches == (Pitch("G", 0, 4),)
        )
        chord = next(event for event in soprano if event.kind == "chord")
        rest = next(event for event in soprano if event.kind == "rest")
        tied_start = next(event for event in soprano if "start" in event.pitch_ties)
        tied_stop = next(event for event in soprano if "stop" in event.pitch_ties)
        lyric = dotted.lyrics[0]

        self.assertEqual((Fraction(0), Fraction(3, 2)), (dotted.onset, dotted.duration))
        self.assertEqual(
            ("note", (Pitch("G", 0, 4),)), (dotted.kind, dotted.sounding_pitches)
        )
        self.assertEqual(Fraction(3, 2), chord.onset)
        self.assertEqual((Pitch("D", 0, 4), Pitch("F", 1, 4)), chord.pitches)
        self.assertEqual((Pitch("D", 0, 4), Pitch("F", 1, 4)), chord.sounding_pitches)
        self.assertEqual((Fraction(5, 2), Fraction(1, 2)), (rest.onset, rest.duration))
        self.assertEqual((0, Fraction(3)), (tied_start.measure_index, tied_start.onset))
        self.assertEqual((1, Fraction(0)), (tied_stop.measure_index, tied_stop.onset))
        self.assertTrue(all(event.voice_id == "1" for event in soprano))
        self.assertEqual(
            ("星", "2", "begin", True),
            (lyric.text, lyric.number, lyric.syllabic, lyric.extend),
        )
        self.assertEqual(
            ("光", "2", "end", True),
            (
                tied_stop.lyrics[0].text,
                tied_stop.lyrics[0].number,
                tied_stop.lyrics[0].syllabic,
                tied_stop.lyrics[0].extend,
            ),
        )
        self.assertTrue(
            all(
                event.sounding_pitches == event.pitches
                for part in model.parts
                if part.transpose_semitones == 0
                for event in part.events
                if event.kind != "rest"
            )
        )
        self.assertEqual(2, len(model.measures))
        self.assertEqual(
            (4, 4, 0, "major", Fraction(4)),
            (
                model.measures[0].beats,
                model.measures[0].beat_type,
                model.measures[0].fifths,
                model.measures[0].mode,
                model.measures[0].duration,
            ),
        )
        self.assertEqual(
            (2, 2, 1, "major", Fraction(4)),
            (
                model.measures[1].beats,
                model.measures[1].beat_type,
                model.measures[1].fifths,
                model.measures[1].mode,
                model.measures[1].duration,
            ),
        )

    def test_g_major_fixture_has_expected_written_sequence_and_context(self):
        from src.music_convert.musicxml_io import load_musicxml

        model = load_musicxml(self.fixture("g-major-two-bars.musicxml"))
        soprano = model.parts[0]
        self.assertEqual("Soprano", soprano.name)
        self.assertEqual(
            [Pitch("G", 0, 4), Pitch("A", 0, 4), Pitch("B", 0, 4), Pitch("C", 0, 5)],
            [event.pitches[0] for event in soprano.events[:4]],
        )
        self.assertEqual(1, model.measures[0].fifths)
        self.assertEqual("major", model.measures[0].mode)
        self.assertEqual((4, 4), (model.measures[0].beats, model.measures[0].beat_type))
        self.assertTrue(all(event.sounding_pitches for event in soprano.events))

    def test_mxl_archive_is_parsed_directly_and_retained_verbatim(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from zipfile import ZipFile

        from src.music_convert.musicxml_io import load_musicxml

        payload = self.fixture("g-major-two-bars.musicxml").read_bytes()
        container = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b"<container><rootfiles><rootfile "
            b'full-path="score.musicxml" '
            b'media-type="application/vnd.recordare.musicxml+xml"'
            b"/></rootfiles></container>"
        )
        with TemporaryDirectory() as directory:
            archive_path = Path(directory) / "score.mxl"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("META-INF/container.xml", container)
                archive.writestr("score.musicxml", payload)
            original_archive = archive_path.read_bytes()
            model = load_musicxml(archive_path)

        self.assertEqual("G Major Two Bars", model.title)
        self.assertEqual(original_archive, model.source_musicxml)

    def test_fractional_tuplet_timing_stays_exact(self):
        from music21 import duration, note, stream

        from src.music_convert.musicxml_io import score_to_model

        score = stream.Score()
        part = stream.Part(id="Tuplets")
        measure = stream.Measure(number=1)
        first = note.Note("C4")
        first.duration = duration.Duration(Fraction(1, 3))
        second = note.Note("D4")
        second.duration = duration.Duration(Fraction(1, 3))
        measure.insert(0, first)
        measure.insert(Fraction(1, 3), second)
        part.append(measure)
        score.append(part)

        events = score_to_model(score).parts[0].events
        self.assertEqual(
            [(Fraction(0), Fraction(1, 3)), (Fraction(1, 3), Fraction(1, 3))],
            [(event.onset, event.duration) for event in events],
        )

    def test_musicxml_pickup_marker_keeps_actual_measure_length(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from src.music_convert.musicxml_io import load_musicxml

        pickup_xml = """<?xml version="1.0"?>
        <score-partwise version="4.0">
          <part-list><score-part id="P"><part-name>Soprano</part-name></score-part></part-list>
          <part id="P"><measure number="0" implicit="yes">
            <attributes><divisions>2</divisions><key><fifths>0</fifths><mode>major</mode></key>
              <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
            <note><pitch><step>G</step><octave>4</octave></pitch>
              <duration>1</duration><type>eighth</type></note>
          </measure></part>
        </score-partwise>"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pickup.musicxml"
            path.write_text(pickup_xml, encoding="utf-8")
            model = load_musicxml(path)

        self.assertTrue(model.measures[0].pickup)
        self.assertEqual(Fraction(1, 2), model.measures[0].duration)

    def test_score_to_model_keeps_explicit_source_bytes(self):
        from music21 import converter

        from src.music_convert.musicxml_io import score_to_model

        source_bytes = b"<original musicxml bytes>"
        score = converter.parse(str(self.fixture("g-major-two-bars.musicxml")))
        model = score_to_model(score, source_musicxml=source_bytes)
        self.assertEqual(source_bytes, model.source_musicxml)


if __name__ == "__main__":
    unittest.main()
