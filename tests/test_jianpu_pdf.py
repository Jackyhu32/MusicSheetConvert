from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader

from src.music_convert.musicxml_io import load_musicxml
from src.render.jianpu_pdf import render_jianpu_pdf


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
            self.assertIn("1 2 3 4 5 6 7 0", text)

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
