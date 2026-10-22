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

    def showPage(self):
        self.page_breaks += 1

    def save(self):
        self.output_path.write_bytes(b"%PDF-test")


def render_with_canvas_spy(score):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "layout-spy.pdf"
        canvas = RecordingCanvas(output, (0, 0))
        with patch("src.render.jianpu_pdf.Canvas", return_value=canvas):
            render_jianpu_pdf(score, output, notation="fixed")
    return canvas


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
        canvas = render_with_canvas_spy(score)
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
            if (event.measure_index, event.onset) in ((0, Fraction(3, 2)), (1, Fraction(2)))
        ]

        for event in target_events:
            measure_position = next(
                index for index, item in enumerate(score.measures)
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
                    degree, octave = map_pitch(pitch, notation="fixed")
                    suffix = f"^{octave}" if octave > 0 else f"v{-octave}" if octave < 0 else ""
                    token_parts.append(f"{degree}{suffix}")
                token = "+".join(token_parts)
            self.assertIn(
                (expected_x, token), note_calls,
                f"event at measure {event.measure_index}, beat {event.onset}",
            )

        first_measure_event_x = next(
            x for x, token in note_calls if token == "2+#4"
        )
        next_measure_event_x = next(
            x for x, token in note_calls if token == "5" and x > system_x + measure_width
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
        canvas = render_with_canvas_spy(score)

        def event_y(event):
            degree, octave = map_pitch(
                event.effective_sounding_pitches[0], notation="fixed"
            )
            suffix = f"^{octave}" if octave > 0 else f"v{-octave}" if octave < 0 else ""
            token = f"{degree}{suffix}"
            return next(
                y
                for font, x, y, text in canvas.string_calls
                if font == ("Helvetica", 11) and x == 150.0 and text == token
            )

        self.assertNotEqual(event_y(voice_events["1"]), event_y(voice_events["2"]))

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
        canvas = render_with_canvas_spy(score)

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
                soprano_label_index + 1:alto_label_index
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

            def save(self):
                self.output_path.write_bytes(b"%PDF-test")

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
                degree, octave = map_pitch(pitch, notation="fixed")
                suffix = f"^{octave}" if octave > 0 else f"v{-octave}" if octave < 0 else ""
                tokens.append(f"{degree}{suffix}")
            return "+".join(tokens)

        expected_tokens = Counter(token_for(event) for event in common_onset_events)
        actual_tokens = Counter(
            text for _font, x, _y, text in note_calls if x == 150.0
        )
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
        self.assertEqual(len(score.measures), len(canvas.line_calls))


class JianpuPdfTests(unittest.TestCase):
    def fixture(self, name):
        return Path(__file__).parent / "fixtures" / name

    def test_writes_readable_one_page_pdf_and_creates_parent_directory(self):
        score = load_musicxml(self.fixture("g-major-two-bars.musicxml"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "jianpu.pdf"
            result = render_jianpu_pdf(score, output, title="Renderer Test")

            self.assertEqual(output, result)
            self.assertTrue(output.exists())
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
            reader = PdfReader(str(output))
            self.assertEqual(1, len(reader.pages))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("Renderer Test", text)
            self.assertIn("Soprano", text)
            self.assertRegex(text, r"1\s+2\s+3\s+4\s+5\s+6\s+7\s+0")

    def test_uses_each_measure_key_mode_and_effective_sounding_pitch(self):
        score = load_musicxml(self.fixture("c-major-to-a-minor.musicxml"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mode-change.pdf"
            render_jianpu_pdf(score, output, notation="movable", tonic="C")
            text = PdfReader(str(output)).pages[0].extract_text()

        # C maps to 1 in C major but 6 when tonic C uses the minor context.
        self.assertIn("1", text)
        self.assertIn("6", text)

        satbb = load_musicxml(self.fixture("satbb-two-measures.musicxml"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sounding-pitch.pdf"
            render_jianpu_pdf(satbb, output, notation="fixed")
            pages = PdfReader(str(output)).pages
            text = "\n".join(page.extract_text() or "" for page in pages)

        # The first Tenor pitch is written C4 but sounds C3.
        self.assertIn("Tenor", text)
        self.assertIn("1v", text)

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


if __name__ == "__main__":
    unittest.main()
