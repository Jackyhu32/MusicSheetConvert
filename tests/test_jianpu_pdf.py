import copy
import multiprocessing
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth

from src.music_convert.jianpu import map_pitch
from src.music_convert.model import (
    Lyric,
    MeasureContext,
    Pitch,
    ScoreEvent,
    ScoreModel,
    ScorePart,
)
from src.music_convert.musicxml_io import load_musicxml
from src.render.jianpu_pdf import event_x, render_jianpu_pdf


class RecordingCanvas:
    def __init__(self, output_path, pagesize):
        self.output_path = Path(output_path)
        self.string_calls = []
        self.line_calls = []
        self.circle_calls = []
        self.path_calls = []
        self.draw_coordinates = []
        self.page_breaks = 0
        self.font = (None, None)

    def setTitle(self, title):
        pass

    def setFont(self, name, size):
        self.font = (name, size)

    def setLineWidth(self, width):
        pass

    def drawString(self, x, y, text):
        self.string_calls.append((self.font, x, y, text))
        self.draw_coordinates.append((x, y))

    def drawCentredString(self, x, y, text):
        self.string_calls.append((self.font, x, y, text))
        self.draw_coordinates.append((x, y))

    def line(self, x1, y1, x2, y2):
        self.line_calls.append((x1, y1, x2, y2))
        self.draw_coordinates.extend(((x1, y1), (x2, y2)))

    def circle(self, x, y, radius, stroke=1, fill=0):
        self.circle_calls.append((x, y, radius, stroke, fill))
        self.draw_coordinates.append((x, y))

    def beginPath(self):
        return RecordingPath()

    def drawPath(self, path, stroke=1, fill=0):
        self.path_calls.append((path.commands, stroke, fill))
        for command in path.commands:
            coordinates = command[1:]
            self.draw_coordinates.extend(zip(coordinates[::2], coordinates[1::2]))

    def showPage(self):
        self.page_breaks += 1

    def save(self):
        self.output_path.write_bytes(b"%PDF-test")


class RecordingPath:
    def __init__(self):
        self.commands = []

    def moveTo(self, x, y):
        self.commands.append(("moveTo", x, y))

    def curveTo(self, x1, y1, x2, y2, x3, y3):
        self.commands.append(("curveTo", x1, y1, x2, y2, x3, y3))


def render_with_canvas_spy(score, **options):
    ignore_ties = options.pop("ignore_ties", False)
    strip_lyrics = options.pop("strip_lyrics", True)
    score = copy.deepcopy(score)
    for part in score.parts:
        part.events = [
            replace(
                event,
                lyrics=() if strip_lyrics else event.lyrics,
                **({"pitch_ties": ()} if ignore_ties else {}),
            )
            for event in part.events
        ]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "layout-spy.pdf"
        canvas = RecordingCanvas(output, (0, 0))
        options.setdefault("notation", "fixed")
        with patch("src.render.jianpu_pdf.Canvas", return_value=canvas):
            render_jianpu_pdf(score, output, **options)
    return canvas


def score_from_sequence(
    sequence, *, duration=None, measure_modes=None, title="Notation Test"
):
    """Build one-lane measures from duration/kind/pitches/ties/lyrics tuples."""
    measures = []
    part = ScorePart("P1", "Test Part")
    for measure_index, items in enumerate(sequence):
        measure_duration = (
            duration[measure_index] if isinstance(duration, tuple) else duration
        )
        if measure_duration is None:
            measure_duration = sum((item[0] for item in items), Fraction(0))
        measures.append(
            MeasureContext(
                measure_index,
                str(measure_index + 1),
                measure_duration,
                0,
                measure_modes[measure_index] if measure_modes else "major",
                None,
                None,
            )
        )
        onset = Fraction(0)
        for item_duration, kind, pitches, ties, lyrics in items:
            part.events.append(
                ScoreEvent(
                    "P1",
                    measure_index,
                    "1",
                    onset,
                    item_duration,
                    kind,
                    pitches=pitches,
                    sounding_pitches=pitches,
                    pitch_ties=ties,
                    lyrics=lyrics,
                )
            )
            onset += item_duration
    return ScoreModel(title, [part], measures)


def _render_in_child(score, output_path, result_queue):
    try:
        render_jianpu_pdf(score, output_path, notation="fixed")
    except ValueError as error:
        result_queue.put((type(error).__name__, str(error)))
    else:
        result_queue.put(("success", ""))


def tied_measure_chain(count):
    c4 = Pitch("C", 0, 4)
    sequence = []
    for index in range(count):
        tie_state = (
            "start" if index == 0 else "stop" if index == count - 1 else "continue"
        )
        sequence.append([(Fraction(4), "note", (c4,), (tie_state,), ())])
    return score_from_sequence(sequence, duration=(Fraction(4),) * count)


def dense_score(part_count=6, lane_count=8, measure_count=10):
    measures = [
        MeasureContext(
            index=index,
            number=f"M{index + 1}",
            duration=Fraction(4),
            fifths=0,
            mode="major",
            beats=4,
            beat_type=4,
        )
        for index in range(measure_count)
    ]
    parts = []
    for part_index in range(part_count):
        part_id = f"P{part_index + 1}"
        part = ScorePart(part_id, f"Source Part {part_index + 1}")
        part.events = [
            ScoreEvent(
                part_id,
                measure.index,
                "1",
                Fraction(0),
                Fraction(4),
                "rest",
                staff_number=str(lane + 1),
            )
            for measure in measures
            for lane in range(lane_count)
        ]
        parts.append(part)
    return ScoreModel("Dense Layout", parts, measures)


def late_long_chord_score(pitch_count=80):
    measure = MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)
    part = ScorePart("P1", "Chord Part")
    pitches = (Pitch("C", 0, 4),) * pitch_count
    part.events = [
        ScoreEvent("P1", 0, "1", Fraction(0), Fraction(3), "rest"),
        ScoreEvent(
            "P1",
            0,
            "1",
            Fraction(3),
            Fraction(1),
            "chord",
            pitches=pitches,
            sounding_pitches=pitches,
        ),
    ]
    return ScoreModel("Chord Bounds", [part], [measure])


def chord_crossing_measure_boundary_score():
    measures = [
        MeasureContext(index, str(index + 1), Fraction(4), 0, "major", 4, 4)
        for index in range(2)
    ]
    part = ScorePart("P1", "Overlap Part")
    chord_pitches = (Pitch("C", 0, 4),) * 9
    part.events = [
        ScoreEvent("P1", 0, "1", Fraction(0), Fraction(3), "rest"),
        ScoreEvent(
            "P1",
            0,
            "1",
            Fraction(3),
            Fraction(1),
            "chord",
            pitches=chord_pitches,
            sounding_pitches=chord_pitches,
        ),
        ScoreEvent(
            "P1",
            1,
            "1",
            Fraction(0),
            Fraction(4),
            "note",
            pitches=(Pitch("D", 0, 4),),
            sounding_pitches=(Pitch("D", 0, 4),),
        ),
    ]
    return ScoreModel("Cell Bounds", [part], measures)


def chord_overlapping_next_onset_score():
    measure = MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)
    part = ScorePart("P1", "Same Measure Part")
    pitches = (Pitch("C", 0, 4),) * 14
    part.events = [
        ScoreEvent(
            "P1",
            0,
            "1",
            Fraction(0),
            Fraction(1),
            "chord",
            pitches=pitches,
            sounding_pitches=pitches,
        ),
        ScoreEvent("P1", 0, "1", Fraction(1), Fraction(3), "rest"),
    ]
    return ScoreModel("Same Measure Bounds", [part], [measure])


class JianpuLayoutTests(unittest.TestCase):
    def test_event_x_scales_onset_within_measure(self):
        first_beat_x = event_x(Fraction(1, 2), Fraction(4), 80.0, 400.0)
        later_beat_x = event_x(Fraction(2), Fraction(4), 80.0, 400.0)

        self.assertEqual(130.0, first_beat_x)
        self.assertLess(first_beat_x, later_beat_x)

    def test_event_x_rejects_zero_or_negative_measure_duration(self):
        for duration in (Fraction(0), Fraction(-1)):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                event_x(Fraction(0), duration, 80.0, 400.0)

    def test_canvas_uses_beat_and_measure_positions_for_events(self):
        score = load_musicxml(
            Path(__file__).parent / "fixtures" / "satbb-two-measures.musicxml"
        )
        canvas = render_with_canvas_spy(score, ignore_ties=True)
        part = score.parts[0]
        measure_by_index = {measure.index: measure for measure in score.measures}
        system_x = 150.0
        measure_width = (841.8897637795277 - 36.0 - system_x) / len(score.measures)
        note_calls = [
            (x, text)
            for font, x, _y, text in canvas.string_calls
            if font == ("Helvetica", 11)
        ]
        target_events = [
            event
            for event in part.events
            if (event.measure_index, event.onset)
            in ((0, Fraction(3, 2)), (1, Fraction(2)))
        ]

        for event in target_events:
            measure_position = next(
                index
                for index, item in enumerate(score.measures)
                if item.index == event.measure_index
            )
            expected_x = (
                system_x
                + measure_position * measure_width
                + float(event.onset / measure_by_index[event.measure_index].duration)
                * measure_width
            )
            if event.kind == "rest":
                token = "0"
            else:
                token_parts = []
                for pitch in event.effective_sounding_pitches:
                    degree, _octave = map_pitch(pitch, notation="fixed")
                    token_parts.append(degree)
                token = "+".join(token_parts)
            self.assertIn(
                (expected_x, token),
                note_calls,
                f"event at measure {event.measure_index}, beat {event.onset}",
            )

        first_measure_event_x = next(x for x, token in note_calls if token == "2+#4")
        next_measure_event_x = next(
            x
            for x, token in note_calls
            if token == "5" and x > system_x + measure_width
        )
        self.assertGreater(next_measure_event_x, first_measure_event_x)

    def test_same_staff_voice_lanes_at_shared_onset_have_distinct_y(self):
        score = load_musicxml(
            Path(__file__).parent / "fixtures" / "satbb-two-measures.musicxml"
        )
        soprano = score.parts[0]
        voice_events = {
            event.voice_id: event
            for event in soprano.events
            if event.measure_index == 0
            and event.staff_number == "1"
            and event.onset == 0
            and event.kind == "note"
        }
        self.assertEqual({"1", "2"}, set(voice_events))
        canvas = render_with_canvas_spy(score, ignore_ties=True)

        soprano_label_y = next(
            y
            for font, x, y, text in canvas.string_calls
            if font == ("Helvetica-Bold", 11) and x == 36 and text == soprano.name
        )
        lane_note_ys = {
            y
            for font, x, y, text in canvas.string_calls
            if font == ("Helvetica", 11)
            and x == 150.0
            and soprano_label_y - 35 <= y <= soprano_label_y
        }
        self.assertGreaterEqual(len(lane_note_ys), 2)

    def test_dynamic_part_rows_keep_lower_part_clear_of_all_lanes(self):
        score = load_musicxml(
            Path(__file__).parent / "fixtures" / "satbb-two-measures.musicxml"
        )
        soprano = score.parts[0]
        source_events = tuple(soprano.events)
        for staff_number in range(2, 8):
            soprano.events.extend(
                replace(event, staff_number=str(staff_number))
                for event in source_events
                if event.staff_number == "1" and event.voice_id == "1"
            )
        canvas = render_with_canvas_spy(score, ignore_ties=True)

        label_positions = {
            text: index
            for index, (font, x, _y, text) in enumerate(canvas.string_calls)
            if font == ("Helvetica-Bold", 11) and x == 36
        }
        soprano_label_index = label_positions["Soprano"]
        alto_label_index = label_positions["Alto"]
        alto_label_y = canvas.string_calls[alto_label_index][2]
        soprano_lane_ys = [
            y
            for font, _x, y, _text in canvas.string_calls[
                soprano_label_index + 1 : alto_label_index
            ]
            if font == ("Helvetica", 11)
        ]

        self.assertEqual(8, len(set(soprano_lane_ys)))
        self.assertGreaterEqual(min(soprano_lane_ys) - alto_label_y, 20.0)

    def test_renderer_aligns_beats_and_separates_staff_lanes(self):
        score = load_musicxml(
            Path(__file__).parent / "fixtures" / "satbb-two-measures.musicxml"
        )
        soprano = score.parts[0]
        soprano.events.extend(
            replace(event, staff_number="2")
            for event in tuple(soprano.events)
            if event.staff_number == "1" and event.voice_id == "1"
        )

        canvas_instances = []

        class RecordingCanvas:
            def __init__(self, output_path, pagesize):
                self.output_path = Path(output_path)
                self.string_calls = []
                self.line_calls = []
                self.font = (None, None)
                canvas_instances.append(self)

            def setTitle(self, title):
                pass

            def setFont(self, name, size):
                self.font = (name, size)

            def setLineWidth(self, width):
                pass

            def drawString(self, x, y, text):
                self.string_calls.append((self.font, x, y, text))

            def drawCentredString(self, x, y, text):
                self.string_calls.append((self.font, x, y, text))

            def line(self, x1, y1, x2, y2):
                self.line_calls.append((x1, y1, x2, y2))

            def circle(self, x, y, radius, stroke=1, fill=0):
                pass

            def beginPath(self):
                return RecordingPath()

            def drawPath(self, path, stroke=1, fill=0):
                pass

            def save(self):
                self.output_path.write_bytes(b"%PDF-test")

        for part in score.parts:
            part.events = [
                replace(event, lyrics=(), pitch_ties=()) for event in part.events
            ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "satbb-spy.pdf"
            with patch("src.render.jianpu_pdf.Canvas", RecordingCanvas):
                render_jianpu_pdf(score, output, notation="fixed")

        canvas = canvas_instances[-1]
        note_calls = [
            call for call in canvas.string_calls if call[0] == ("Helvetica", 11)
        ]
        part_labels = [
            text
            for font, _x, _y, text in canvas.string_calls
            if font == ("Helvetica-Bold", 11)
        ]
        self.assertEqual([part.name for part in score.parts], part_labels)

        common_onset_events = [
            event
            for part in score.parts
            for event in part.events
            if event.measure_index == 0 and event.onset == 0
        ]

        def token_for(event):
            if event.kind == "rest":
                return "0"
            tokens = []
            for pitch in event.effective_sounding_pitches:
                degree, _octave = map_pitch(pitch, notation="fixed")
                tokens.append(degree)
            return "+".join(tokens)

        expected_tokens = Counter(token_for(event) for event in common_onset_events)
        actual_tokens = Counter(text for _font, x, _y, text in note_calls if x == 150.0)
        self.assertEqual(expected_tokens, actual_tokens)

        staff_two_source = next(
            event
            for event in soprano.events
            if event.staff_number == "2"
            and event.voice_id == "1"
            and event.measure_index == 0
            and event.onset == 0
        )
        token = token_for(staff_two_source)
        soprano_label_y = next(
            y
            for font, x, y, text in canvas.string_calls
            if font == ("Helvetica-Bold", 11) and x == 36 and text == soprano.name
        )
        staff_lane_y = {
            y
            for font, x, y, text in note_calls
            if x == 150.0
            and text == token
            and soprano_label_y - 30 <= y <= soprano_label_y
        }
        self.assertEqual(2, len(staff_lane_y))

        measure_numbers = [
            text
            for font, _x, _y, text in canvas.string_calls
            if font == ("Helvetica", 9)
        ]
        self.assertEqual(
            [measure.number for measure in score.measures], measure_numbers
        )
        barlines = [call for call in canvas.line_calls if call[0] == call[2]]
        self.assertEqual(len(score.measures), len(barlines))


class JianpuPdfTests(unittest.TestCase):
    def fixture(self, name):
        return Path(__file__).parent / "fixtures" / name

    def test_writes_readable_one_page_pdf_and_creates_parent_directory(self):
        score = score_from_sequence(
            [
                [
                    (Fraction(1), "note", (Pitch("C", 0, 4),), (), ()),
                    (Fraction(1), "note", (Pitch("D", 0, 4),), (), ()),
                    (Fraction(2), "rest", (), (), ()),
                ],
            ]
        )
        score.parts[0].name = "Soprano"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "jianpu.pdf"
            result = render_jianpu_pdf(
                score, output, title="Renderer Test", notation="fixed"
            )

            self.assertEqual(output, result)
            self.assertTrue(output.exists())
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
            reader = PdfReader(str(output))
            self.assertEqual(1, len(reader.pages))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("Renderer Test", text)
            self.assertIn("Soprano", text)
            self.assertRegex(text, r"1\s+2\s+0")

    def test_uses_each_measure_key_mode_and_effective_sounding_pitch(self):
        score = load_musicxml(self.fixture("c-major-to-a-minor.musicxml"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mode-change.pdf"
            render_jianpu_pdf(score, output, notation="movable", tonic="C")
            text = PdfReader(str(output)).pages[0].extract_text()

        # C maps to 1 in C major but 6 when tonic C uses the minor context.
        self.assertIn("1", text)
        self.assertIn("6", text)

        measure = MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)
        tenor = ScorePart("P1", "Tenor")
        tenor.events = [
            ScoreEvent(
                "P1",
                0,
                "1",
                Fraction(0),
                Fraction(1),
                "note",
                pitches=(Pitch("C", 0, 4),),
                sounding_pitches=(Pitch("C", 0, 3),),
            ),
            ScoreEvent("P1", 0, "1", Fraction(1), Fraction(3), "rest"),
        ]
        sounding_score = ScoreModel("Sounding Pitch", [tenor], [measure])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sounding-pitch.pdf"
            render_jianpu_pdf(sounding_score, output, notation="fixed")
            text = PdfReader(str(output)).pages[0].extract_text()

        self.assertIn("Tenor", text)
        self.assertIn("1", text)
        canvas = render_with_canvas_spy(sounding_score)
        note_y = next(
            y
            for font, _x, y, token in canvas.string_calls
            if font == ("Helvetica", 11) and token == "1"
        )
        self.assertTrue(any(y < note_y for _x, y, *_ in canvas.circle_calls))

    def test_rejects_score_with_validation_issues_before_writing(self):
        score = load_musicxml(self.fixture("g-major-two-bars.musicxml"))
        score.requires_review = True
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "invalid.pdf"

            with self.assertRaisesRegex(ValueError, "validation"):
                render_jianpu_pdf(score, output)

            self.assertFalse(output.exists())

    def test_dense_score_paginates_with_all_draw_coordinates_inside_page(self):
        score = dense_score(part_count=5, lane_count=3, measure_count=10)
        source_part_names = [part.name for part in score.parts]
        source_events = [tuple(part.events) for part in score.parts]
        source_measure_numbers = [measure.number for measure in score.measures]

        canvas = render_with_canvas_spy(score)

        page_width, page_height = landscape(A4)
        self.assertGreater(canvas.page_breaks + 1, 1)
        self.assertTrue(canvas.draw_coordinates)
        for x, y in canvas.draw_coordinates:
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x, page_width)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y, page_height)
        for (font_name, font_size), x, _y, text in canvas.string_calls:
            text_width = stringWidth(text, font_name, font_size)
            if font_size == 18:
                self.assertGreaterEqual(x - text_width / 2, 0)
                self.assertLessEqual(x + text_width / 2, page_width)
            else:
                self.assertGreaterEqual(x, 0)
                self.assertLessEqual(x + text_width, page_width)

        rendered_labels = [
            text
            for font, x, _y, text in canvas.string_calls
            if font == ("Helvetica-Bold", 11) and x == 36
        ]
        self.assertEqual(set(source_part_names), set(rendered_labels))
        self.assertEqual(
            sum(len(part.events) for part in score.parts),
            sum(
                font == ("Helvetica", 11) and text == "0"
                for font, _x, _y, text in canvas.string_calls
            ),
        )
        rendered_measure_numbers = {
            text
            for font, _x, _y, text in canvas.string_calls
            if font == ("Helvetica", 9)
        }
        self.assertEqual(set(source_measure_numbers), rendered_measure_numbers)
        self.assertEqual(source_events, [tuple(part.events) for part in score.parts])
        self.assertEqual(source_part_names, [part.name for part in score.parts])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dense-score.pdf"
            render_jianpu_pdf(score, output, notation="fixed")
            pages = PdfReader(str(output)).pages

        self.assertGreater(len(pages), 1)
        extracted_text = "\n".join(page.extract_text() or "" for page in pages)
        for page in pages:
            page_text = page.extract_text() or ""
            for part_name in source_part_names:
                self.assertIn(part_name, page_text)
        for measure_number in source_measure_numbers:
            self.assertIn(measure_number, extracted_text)

    def test_rejects_single_part_whose_lanes_cannot_fit_vertically(self):
        score = dense_score(part_count=1, lane_count=50, measure_count=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "too-tall.pdf"

            with self.assertRaisesRegex(ValueError, "cannot fit"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_rejects_ensemble_whose_complete_lane_rows_cannot_fit(self):
        score = dense_score(part_count=6, lane_count=8, measure_count=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ensemble-too-tall.pdf"

            with self.assertRaisesRegex(ValueError, "ensemble.*cannot fit"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_rejects_chord_token_crossing_measure_barline_into_next_event(self):
        score = chord_crossing_measure_boundary_score()
        chord_token = "+".join(["1"] * 9)
        chord_width = stringWidth(chord_token, "Helvetica", 11)
        page_width, _ = landscape(A4)
        system_width = page_width - 36.0 - 150.0
        measure_width = system_width / 2
        chord_x = 150.0 + measure_width * Fraction(3, 4)
        barline_x = 150.0 + measure_width
        self.assertGreater(chord_x + chord_width, barline_x)
        self.assertLess(chord_x + chord_width, page_width - 36.0)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cross-measure-chord.pdf"

            with self.assertRaisesRegex(ValueError, "rhythmic cell"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_rejects_chord_token_overlapping_next_onset_in_same_lane(self):
        score = chord_overlapping_next_onset_score()
        token = "+".join(["1"] * 14)
        token_width = stringWidth(token, "Helvetica", 11)
        system_width = landscape(A4)[0] - 36.0 - 150.0
        measure_width = system_width
        next_onset_x = 150.0 + measure_width / 4
        self.assertGreater(150.0 + token_width, next_onset_x)
        self.assertLess(150.0 + token_width, 150.0 + measure_width)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "same-measure-overlap.pdf"

            with self.assertRaisesRegex(ValueError, "rhythmic cell"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_rejects_late_long_chord_that_would_overflow_page_width(self):
        score = late_long_chord_score()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "wide-chord.pdf"

            with self.assertRaisesRegex(ValueError, "text.*fit.*horizontal"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_rejects_title_or_part_label_that_exceeds_its_horizontal_region(self):
        score = dense_score(part_count=1, lane_count=1, measure_count=1)
        cases = (
            {"title": "A" * 200},
            {"part_name": "A" * 200},
        )
        for options in cases:
            with self.subTest(options=tuple(options)):
                if "part_name" in options:
                    score.parts[0].name = options["part_name"]
                    render_options = {}
                else:
                    render_options = options
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "wide-label.pdf"
                    with self.assertRaisesRegex(ValueError, "text.*fit.*horizontal"):
                        render_jianpu_pdf(
                            score, output, notation="fixed", **render_options
                        )
                    self.assertFalse(output.exists())

    def test_canvas_draws_quarter_dotted_short_rest_chord_and_octave_marks(self):
        c4, d4, e4, f4 = (Pitch(step, 0, 4) for step in "CDEF")
        c5, g3 = Pitch("C", 0, 5), Pitch("G", 0, 3)
        score = score_from_sequence(
            [
                [
                    (Fraction(1), "note", (c4,), (), ()),
                    (Fraction(3, 2), "note", (d4,), (), ()),
                    (Fraction(1, 2), "note", (e4,), (), ()),
                    (Fraction(1, 4), "note", (f4,), (), ()),
                    (Fraction(1, 4), "rest", (), (), ()),
                    (Fraction(1), "chord", (c5, g3), (), ()),
                ]
            ]
        )

        canvas = render_with_canvas_spy(score)
        note_tokens = [
            text
            for font, _x, _y, text in canvas.string_calls
            if font == ("Helvetica", 11)
        ]
        expected_tokens = [
            "0"
            if event.kind == "rest"
            else "+".join(
                map_pitch(pitch, notation="fixed")[0]
                for pitch in event.effective_sounding_pitches
            )
            for event in score.parts[0].events
        ]
        self.assertEqual(expected_tokens, note_tokens)
        self.assertEqual(3, len(canvas.circle_calls))
        self.assertEqual([], canvas.path_calls)
        quarter_x, quarter_y = next(
            (x, y)
            for font, x, y, token in canvas.string_calls
            if font == ("Helvetica", 11) and token == "1"
        )
        self.assertFalse(
            any(abs(x - quarter_x) < 10 for x, _y, *_rest in canvas.circle_calls)
        )
        self.assertFalse(
            any(
                x1 == quarter_x and y1 < quarter_y
                for x1, y1, _x2, _y2 in canvas.line_calls
            )
        )
        self.assertGreaterEqual(
            sum(y1 == y2 for _x1, y1, _x2, y2 in canvas.line_calls), 5
        )

    def test_canvas_draws_long_note_duration_dashes(self):
        score = score_from_sequence(
            [
                [
                    (Fraction(4), "note", (Pitch("C", 0, 4),), (), ()),
                ]
            ]
        )

        canvas = render_with_canvas_spy(score)

        self.assertGreaterEqual(
            sum(y1 == y2 for _x1, y1, _x2, y2 in canvas.line_calls), 2
        )

    def test_canvas_draws_one_curve_for_only_the_pitch_tied_in_a_chord(self):
        c4, e4, f4 = Pitch("C", 0, 4), Pitch("E", 0, 4), Pitch("F", 0, 4)
        score = score_from_sequence(
            [
                [
                    (Fraction(1), "chord", (c4, e4), ("start", "none"), ()),
                    (Fraction(1), "chord", (c4, f4), ("stop", "none"), ()),
                    (Fraction(2), "rest", (), (), ()),
                ]
            ],
            duration=(Fraction(4),),
        )

        canvas = render_with_canvas_spy(score)

        self.assertEqual(1, len(canvas.path_calls))
        self.assertEqual("curveTo", canvas.path_calls[0][0][1][0])

    def test_movable_note_tokens_match_map_pitch_in_major_and_minor_contexts(self):
        c4 = Pitch("C", 0, 4)
        score = score_from_sequence(
            [
                [(Fraction(4), "note", (c4,), (), ())],
                [(Fraction(4), "note", (c4,), (), ())],
            ],
            duration=(Fraction(4), Fraction(4)),
            measure_modes=("major", "minor"),
        )

        canvas = render_with_canvas_spy(score, notation="movable", tonic="C")
        note_tokens = [
            text
            for font, _x, _y, text in canvas.string_calls
            if font == ("Helvetica", 11)
        ]
        expected = [
            map_pitch(c4, tonic="C", key_mode=mode, notation="movable")[0]
            for mode in ("major", "minor")
        ]

        self.assertEqual(expected, note_tokens)

    def test_english_lyrics_render_and_are_extractable_without_cjk_font(self):
        score = score_from_sequence(
            [
                [
                    (
                        Fraction(4),
                        "note",
                        (Pitch("C", 0, 4),),
                        (),
                        (Lyric("hello", syllabic="begin", extend=True),),
                    ),
                ]
            ]
        )
        with (
            patch.dict("os.environ", {"JIANPU_CJK_FONT": ""}),
            tempfile.TemporaryDirectory() as directory,
        ):
            output = Path(directory) / "english-lyrics.pdf"
            render_jianpu_pdf(score, output, notation="fixed")
            text = PdfReader(str(output)).pages[0].extract_text()

        self.assertIn("hello", text)
        self.assertIn("-", text)

    def test_cjk_lyrics_require_an_explicitly_configured_font(self):
        score = score_from_sequence(
            [
                [
                    (Fraction(4), "note", (Pitch("C", 0, 4),), (), (Lyric("春天"),)),
                ]
            ]
        )
        with (
            patch.dict("os.environ", {"JIANPU_CJK_FONT": ""}),
            tempfile.TemporaryDirectory() as directory,
        ):
            output = Path(directory) / "missing-cjk-font.pdf"

            with self.assertRaisesRegex(RuntimeError, "font_path|JIANPU_CJK_FONT"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_cjk_punctuation_only_lyrics_require_font_and_render_without_replacement(
        self,
    ):
        score = score_from_sequence(
            [
                [
                    (Fraction(4), "note", (Pitch("C", 0, 4),), (), (Lyric("？「"),)),
                ]
            ]
        )
        font_path = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
        if not font_path.is_file():
            self.skipTest("WenQuanYi Zen Hei fixture font is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            missing_font_output = Path(directory) / "punctuation-no-font.pdf"
            with (
                patch.dict("os.environ", {"JIANPU_CJK_FONT": ""}),
                self.assertRaisesRegex(RuntimeError, "CJK lyrics require"),
            ):
                render_jianpu_pdf(score, missing_font_output, notation="fixed")
            self.assertFalse(missing_font_output.exists())

            output = Path(directory) / "punctuation-cjk-font.pdf"
            render_jianpu_pdf(score, output, notation="fixed", font_path=font_path)
            extracted = PdfReader(str(output)).pages[0].extract_text()

        self.assertIn("？「", extracted)
        self.assertNotIn("■", extracted)

    def test_vertical_cjk_punctuation_only_lyrics_require_font(self):
        for punctuation in ("︖", "︐", "︰"):
            with self.subTest(punctuation=punctuation):
                score = score_from_sequence(
                    [
                        [
                            (
                                Fraction(4),
                                "note",
                                (Pitch("C", 0, 4),),
                                (),
                                (Lyric(punctuation),),
                            ),
                        ]
                    ]
                )
                with (
                    patch.dict("os.environ", {"JIANPU_CJK_FONT": ""}),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    output = Path(directory) / "vertical-punctuation.pdf"
                    with self.assertRaisesRegex(RuntimeError, "CJK lyrics require"):
                        render_jianpu_pdf(score, output, notation="fixed")
                    self.assertFalse(output.exists())

                    latin_font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
                    if latin_font.is_file():
                        with self.assertRaisesRegex(
                            RuntimeError, "missing required glyphs"
                        ):
                            render_jianpu_pdf(
                                score,
                                output,
                                notation="fixed",
                                font_path=latin_font,
                            )
                        self.assertFalse(output.exists())

    def test_latin_punctuation_only_lyrics_do_not_require_cjk_font(self):
        score = score_from_sequence(
            [
                [
                    (Fraction(4), "note", (Pitch("C", 0, 4),), (), (Lyric("?!,;:"),)),
                ]
            ]
        )
        with (
            patch.dict("os.environ", {"JIANPU_CJK_FONT": ""}),
            tempfile.TemporaryDirectory() as directory,
        ):
            output = Path(directory) / "latin-punctuation.pdf"
            render_jianpu_pdf(score, output, notation="fixed")
            extracted = PdfReader(str(output)).pages[0].extract_text()

        self.assertIn("?!,;:", extracted)

    def test_keeps_cross_measure_tie_together_at_normal_page_break(self):
        c4 = Pitch("C", 0, 4)
        sequence = [[(Fraction(4), "rest", (), (), ())] for _ in range(7)]
        sequence.extend(
            [
                [
                    (Fraction(3), "rest", (), (), ()),
                    (Fraction(1), "note", (c4,), ("start",), ()),
                ],
                [
                    (Fraction(1), "note", (c4,), ("stop",), ()),
                    (Fraction(3), "rest", (), (), ()),
                ],
            ]
        )
        score = score_from_sequence(sequence, duration=(Fraction(4),) * 9)

        canvas = render_with_canvas_spy(score)

        self.assertEqual(1, canvas.page_breaks)
        self.assertEqual(1, len(canvas.path_calls))
        path_commands = canvas.path_calls[0][0]
        self.assertLess(path_commands[0][1], path_commands[1][-2])

    def test_tie_chain_at_system_capacity_groups_and_renders(self):
        score = tied_measure_chain(8)

        canvas = render_with_canvas_spy(score)

        self.assertEqual(0, canvas.page_breaks)
        self.assertEqual(7, len(canvas.path_calls))

    def test_linked_chain_longer_than_system_fails_promptly_before_output(self):
        score = tied_measure_chain(9)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "oversized-tie-chain.pdf"
            result_queue = multiprocessing.Queue()
            process = multiprocessing.Process(
                target=_render_in_child,
                args=(score, str(output), result_queue),
            )
            process.start()
            process.join(timeout=5.0)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail("renderer hung grouping a linked chain over system capacity")

            self.assertEqual(0, process.exitcode)
            result = result_queue.get(timeout=1.0)
            self.assertEqual("ValueError", result[0])
            self.assertIn("linked tie/slur chain", result[1])
            self.assertFalse(output.exists())

    def test_canvas_places_numbered_lyrics_on_distinct_verse_rows(self):
        score = score_from_sequence(
            [
                [
                    (
                        Fraction(4),
                        "note",
                        (Pitch("C", 0, 4),),
                        (),
                        (
                            Lyric("first", number="1"),
                            Lyric("second", number="2"),
                        ),
                    ),
                ]
            ]
        )

        canvas = render_with_canvas_spy(score, strip_lyrics=False)
        verse_rows = {
            text: y
            for font, _x, y, text in canvas.string_calls
            if font == ("Helvetica", 8) and text in {"first", "second"}
        }

        self.assertEqual({"first", "second"}, set(verse_rows))
        self.assertNotEqual(verse_rows["first"], verse_rows["second"])

    def test_draws_a_tie_across_a_measure_barline(self):
        c4 = Pitch("C", 0, 4)
        score = score_from_sequence(
            [
                [(Fraction(1), "note", (c4,), ("start",), ())],
                [(Fraction(1), "note", (c4,), ("stop",), ())],
            ],
            duration=(Fraction(1), Fraction(1)),
        )

        canvas = render_with_canvas_spy(score)

        self.assertEqual(1, len(canvas.path_calls))

    def test_rejects_downward_octave_dots_that_leave_page(self):
        measure = MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)
        parts = []
        for part_index in range(6):
            part = ScorePart(f"P{part_index}", f"Part {part_index}")
            lane_numbers = range(1, 9) if part_index == 5 else range(1, 2)
            for lane_number in lane_numbers:
                pitch = Pitch("C", 0, -40) if lane_number == 8 else Pitch("C", 0, 4)
                part.events.append(
                    ScoreEvent(
                        part.id,
                        0,
                        str(lane_number),
                        Fraction(0),
                        Fraction(4),
                        "note",
                        pitches=(pitch,),
                        sounding_pitches=(pitch,),
                    )
                )
            parts.append(part)
        score = ScoreModel("Downward Bounds", parts, [measure])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downward-octave-overflow.pdf"

            with self.assertRaisesRegex(
                ValueError,
                "octave marks.*vertical bounds|ensemble lane layout cannot fit",
            ):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_octave_dots_on_adjacent_lanes_do_not_overlap(self):
        measure = MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)
        upper = Pitch("C", 0, 3)
        lower = Pitch("C", 0, 5)
        part = ScorePart(
            "P",
            "Two Voices",
            events=[
                ScoreEvent(
                    "P",
                    0,
                    "1",
                    Fraction(0),
                    Fraction(4),
                    "note",
                    pitches=(upper,),
                    sounding_pitches=(upper,),
                ),
                ScoreEvent(
                    "P",
                    0,
                    "2",
                    Fraction(0),
                    Fraction(4),
                    "note",
                    pitches=(lower,),
                    sounding_pitches=(lower,),
                ),
            ],
        )
        score = ScoreModel("Lane Marks", [part], [measure])

        canvas = render_with_canvas_spy(score)
        centers = [
            (x, y)
            for x, y, radius, _stroke, fill in canvas.circle_calls
            if fill and radius == 1.2
        ]

        self.assertEqual(2, len(centers))
        self.assertGreater(abs(centers[0][1] - centers[1][1]), 2.4)

    def test_extension_g_lyrics_require_cjk_font(self):
        score = score_from_sequence(
            [
                [
                    (
                        Fraction(4),
                        "note",
                        (Pitch("C", 0, 4),),
                        (),
                        (Lyric("\U00030000"),),
                    ),
                ]
            ]
        )
        with (
            patch.dict("os.environ", {"JIANPU_CJK_FONT": ""}),
            tempfile.TemporaryDirectory() as directory,
        ):
            output = Path(directory) / "extension-g.pdf"

            with self.assertRaisesRegex(RuntimeError, "CJK lyrics require"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_rejects_configured_font_missing_a_required_cjk_glyph(self):
        font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        if not font_path.is_file():
            self.skipTest("DejaVu Sans is not available")
        score = score_from_sequence(
            [
                [
                    (Fraction(4), "note", (Pitch("C", 0, 4),), (), (Lyric("春"),)),
                ]
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "missing-glyph.pdf"

            with self.assertRaisesRegex(RuntimeError, "missing.*glyph|glyph.*missing"):
                render_jianpu_pdf(score, output, notation="fixed", font_path=font_path)

            self.assertFalse(output.exists())

    def test_canvas_draws_explicit_slur_independent_of_tie_state(self):
        c4 = Pitch("C", 0, 4)
        score = score_from_sequence(
            [
                [
                    (Fraction(2), "note", (c4,), (), ()),
                    (Fraction(2), "note", (Pitch("D", 0, 4),), (), ()),
                ]
            ]
        )
        score.parts[0].events = [
            replace(score.parts[0].events[0], slurs=(("start", "1"),)),
            replace(score.parts[0].events[1], slurs=(("stop", "1"),)),
        ]

        canvas = render_with_canvas_spy(score)

        self.assertEqual(1, len(canvas.path_calls))

    def test_canvas_draws_satbb_tie_arc_across_adjacent_measure_barline(self):
        score = load_musicxml(self.fixture("satbb-two-measures.musicxml"))
        canvas = render_with_canvas_spy(score)

        self.assertTrue(
            any(
                event.measure_index == 0 and "start" in event.pitch_ties
                for event in score.parts[0].events
            )
        )
        self.assertTrue(
            any(
                event.measure_index == 1 and "stop" in event.pitch_ties
                for event in score.parts[0].events
            )
        )
        self.assertGreaterEqual(len(canvas.path_calls), 1)

    def test_cjk_lyrics_use_the_explicit_font_and_remain_extractable(self):
        font_path = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
        if not font_path.is_file():
            self.skipTest("no local CJK TrueType font is available")
        score = score_from_sequence(
            [
                [
                    (Fraction(4), "note", (Pitch("C", 0, 4),), (), (Lyric("春天"),)),
                ]
            ]
        )
        configurations = (
            ({"font_path": font_path}, ""),
            ({}, str(font_path)),
        )
        for options, environment_font in configurations:
            with self.subTest(configured_by="font_path" if options else "environment"):
                with (
                    patch.dict("os.environ", {"JIANPU_CJK_FONT": environment_font}),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    output = Path(directory) / "cjk-lyrics.pdf"
                    render_jianpu_pdf(score, output, notation="fixed", **options)
                    text = PdfReader(str(output)).pages[0].extract_text()

                self.assertIn("春天", text)

    def test_rejects_durations_that_cannot_be_faithfully_notated(self):
        score = load_musicxml(self.fixture("g-major-two-bars.musicxml"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "unsupported-tuplet.pdf"

            with self.assertRaisesRegex(ValueError, "cannot be represented faithfully"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())

    def test_zero_duration_grace_event_fails_without_inventing_a_sentinel(self):
        measure = MeasureContext(0, "1", Fraction(4), 0, "major", 4, 4)
        part = ScorePart("P1", "Grace")
        part.events = [
            ScoreEvent(
                "P1",
                0,
                "1",
                Fraction(0),
                Fraction(0),
                "note",
                pitches=(Pitch("C", 0, 4),),
                sounding_pitches=(Pitch("C", 0, 4),),
                grace=True,
            ),
            ScoreEvent("P1", 0, "1", Fraction(0), Fraction(4), "rest"),
        ]
        score = ScoreModel("Grace", [part], [measure])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "grace.pdf"

            with self.assertRaisesRegex(ValueError, "grace events are zero-duration"):
                render_jianpu_pdf(score, output, notation="fixed")

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
