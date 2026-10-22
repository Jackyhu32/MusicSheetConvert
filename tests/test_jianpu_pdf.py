import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from src.music_convert.jianpu import map_pitch
from src.music_convert.musicxml_io import load_musicxml
from src.render.jianpu_pdf import event_x, render_jianpu_pdf


class RecordingCanvas:
    def __init__(self, output_path, pagesize):
        self.output_path = Path(output_path)
        self.string_calls = []
        self.line_calls = []
        self.font = (None, None)

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


def render_with_canvas_spy(score):
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "layout-spy.pdf"
        canvas = RecordingCanvas(output, (0, 0))
        with patch("src.render.jianpu_pdf.Canvas", return_value=canvas):
            render_jianpu_pdf(score, output, notation="fixed")
    return canvas


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


if __name__ == "__main__":
    unittest.main()
