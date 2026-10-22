from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader

from src.music_convert.musicxml_io import load_musicxml
from src.render.jianpu_pdf import event_x, render_jianpu_pdf


class JianpuLayoutTests(unittest.TestCase):
    def test_event_x_scales_onset_within_measure(self):
        first_beat_x = event_x(Fraction(1, 2), Fraction(4), 80.0, 400.0)
        later_beat_x = event_x(Fraction(2), Fraction(4), 80.0, 400.0)

        self.assertEqual(130.0, first_beat_x)
        self.assertLess(first_beat_x, later_beat_x)

    def test_satbb_parts_share_onset_coordinates_and_labels_appear_once(self):
        score = load_musicxml(
            Path(__file__).parent / "fixtures" / "satbb-two-measures.musicxml"
        )
        measure = score.measures[0]
        common_onset = Fraction(0)
        measure_x = 150.0
        measure_width = 120.0
        coordinates_by_part = {
            part.id: {
                event_x(
                    event.onset,
                    measure.duration,
                    measure_x,
                    measure_width,
                )
                for event in part.events
                if event.measure_index == measure.index
                and event.onset == common_onset
            }
            for part in score.parts
        }
        coordinates_by_part = {
            part_id: coordinates
            for part_id, coordinates in coordinates_by_part.items()
            if coordinates
        }

        self.assertEqual(5, len(coordinates_by_part))
        self.assertEqual({frozenset({measure_x})}, {
            frozenset(coordinates) for coordinates in coordinates_by_part.values()
        })

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "satbb.pdf"
            render_jianpu_pdf(score, output, notation="fixed")
            text = "\n".join(
                page.extract_text() or "" for page in PdfReader(str(output)).pages
            )

        for part in score.parts:
            with self.subTest(part=part.name):
                self.assertEqual(1, text.count(part.name))


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
