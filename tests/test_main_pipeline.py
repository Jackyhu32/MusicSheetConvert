import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.main import run_pipeline
from src.music_convert.musicxml_io import load_musicxml


class MainPipelinePageMergeTests(unittest.TestCase):
    fixtures = Path(__file__).parent / "fixtures"

    def run_pdf_pipeline(self, page_fixtures, expect_failure=False):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        pdf = root / "two-pages.pdf"
        pdf.touch()
        out_dir = root / "output"
        images = [root / "rendered-page-1.png", root / "rendered-page-2.png"]
        for image in images:
            image.touch()

        output_directories = []

        def recognize(image, output_directory, _config):
            index = len(output_directories)
            output_directory = Path(output_directory)
            output_directories.append(output_directory)
            output_directory.mkdir(parents=True, exist_ok=True)
            result = output_directory / f"{image.stem}.musicxml"
            result.write_bytes((self.fixtures / page_fixtures[index]).read_bytes())
            return result

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("src.main.pdf_to_images", return_value=images))
        stack.enter_context(
            patch("src.main.preprocess_image", side_effect=lambda path, _dest: path)
        )
        stack.enter_context(patch("src.main.is_audiveris_available", return_value=True))
        stack.enter_context(patch("src.main.image_to_musicxml", side_effect=recognize))
        midi = stack.enter_context(patch("src.main.core.musicxml_to_midi"))
        jianpu = stack.enter_context(
            patch("src.main.musicxml_to_jianpu_text_file")
        )
        if expect_failure:
            with self.assertRaises(ValueError):
                run_pipeline(pdf, out_dir)
            results = []
        else:
            results = run_pipeline(pdf, out_dir)
        return results, output_directories, midi, jianpu, out_dir

    def test_pdf_pages_are_merged_then_converted_once(self):
        results, output_directories, midi, jianpu, out_dir = self.run_pdf_pipeline(
            ("omr-page-1.musicxml", "omr-page-2.musicxml")
        )

        self.assertEqual(1, len(results))
        self.assertEqual(1, midi.call_count)
        self.assertEqual(1, jianpu.call_count)
        self.assertEqual(2, len(set(output_directories)))
        self.assertEqual(
            ["page-0001", "page-0002"],
            [path.name for path in output_directories],
        )
        self.assertEqual(
            [out_dir / "musicxml" / "pages" / f"page-{index:04d}"
             for index in (1, 2)],
            output_directories,
        )
        merged_path = results[0].musicxml
        self.assertEqual(out_dir / "musicxml" / "merged.musicxml", merged_path)
        merged = load_musicxml(merged_path)
        self.assertEqual(5, len(merged.parts))
        self.assertEqual(
            ["P-S", "P-A", "P-T", "P-BR", "P-B"],
            [part.id for part in merged.parts],
        )
        self.assertEqual([0, 1], [measure.index for measure in merged.measures])
        self.assertTrue(all(len(part.events) == 2 for part in merged.parts))

    def test_renamed_page_part_fails_before_conversion_or_merged_output(self):
        _results, _directories, midi, jianpu, out_dir = self.run_pdf_pipeline(
            ("omr-page-1.musicxml", "omr-page-2-renamed-part.musicxml"),
            expect_failure=True,
        )
        # This assertion is intentionally after a caught pipeline error in the
        # companion helper once page merging is wired into production.
        self.assertEqual(0, midi.call_count)
        self.assertEqual(0, jianpu.call_count)
        self.assertFalse((out_dir / "musicxml" / "merged.musicxml").exists())

    def test_omitted_page_part_fails_before_conversion_or_merged_output(self):
        _results, _directories, midi, jianpu, out_dir = self.run_pdf_pipeline(
            ("omr-page-1.musicxml", "omr-page-2-omitted-part.musicxml"),
            expect_failure=True,
        )
        self.assertEqual(0, midi.call_count)
        self.assertEqual(0, jianpu.call_count)
        self.assertFalse((out_dir / "musicxml" / "merged.musicxml").exists())

    def test_musicxml_input_does_not_invoke_omr_and_returns_one_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "score.musicxml"
            source.write_bytes((self.fixtures / "omr-page-1.musicxml").read_bytes())
            with (
                patch("src.main.image_to_musicxml") as recognize,
                patch("src.main.core.musicxml_to_midi") as midi,
                patch("src.main.musicxml_to_jianpu_text_file") as jianpu,
            ):
                results = run_pipeline(source, root / "output")

        self.assertEqual(1, len(results))
        self.assertEqual(source, results[0].musicxml)
        recognize.assert_not_called()
        midi.assert_called_once()
        jianpu.assert_called_once()


if __name__ == "__main__":
    unittest.main()
