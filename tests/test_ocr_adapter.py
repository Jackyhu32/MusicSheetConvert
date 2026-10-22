import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ocr import AudiverisConfig, image_to_musicxml


class OcrAdapterOutputTests(unittest.TestCase):
    def test_ignores_unrelated_stale_musicxml_when_expected_result_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "page-1.png"
            image.touch()
            output = root / "out"
            output.mkdir()
            stale = output / "old-score.mxl"
            stale.write_bytes(b"stale")

            with (
                patch("src.ocr.find_audiveris", return_value="/mock/audiveris"),
                patch("src.ocr.subprocess.run") as run,
                self.assertRaises(FileNotFoundError),
            ):
                image_to_musicxml(image, output, AudiverisConfig())

            run.assert_called_once()
            self.assertTrue(stale.exists())

    def test_returns_only_the_exact_expected_output_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "page-1.png"
            image.touch()
            output = root / "out"

            def audiveris(_command, **_kwargs):
                output.mkdir(exist_ok=True)
                (output / "page-1-extra.mxl").write_bytes(b"wrong page")
                (output / "page-1.mxl").write_bytes(b"expected page")

            with (
                patch("src.ocr.find_audiveris", return_value="/mock/audiveris"),
                patch("src.ocr.subprocess.run", side_effect=audiveris),
            ):
                result = image_to_musicxml(image, output, AudiverisConfig())
                self.assertEqual("page-1.mxl", result.name)
                self.assertEqual(b"expected page", result.read_bytes())

    def test_page_images_can_write_to_distinct_page_specific_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = []

            def audiveris(command, **_kwargs):
                out_dir = Path(command[command.index("-output") + 1])
                image = Path(command[-1])
                result = out_dir / f"{image.stem}.mxl"
                result.write_bytes(image.name.encode())
                results.append(result)

            with (
                patch("src.ocr.find_audiveris", return_value="/mock/audiveris"),
                patch("src.ocr.subprocess.run", side_effect=audiveris),
            ):
                for page in (1, 2):
                    image = root / f"page-{page}.png"
                    image.touch()
                    page_dir = root / f"page-{page}-output"
                    returned = image_to_musicxml(image, page_dir, AudiverisConfig())
                    self.assertEqual(returned, results[-1])

            self.assertEqual(2, len(set(results)))
            self.assertNotEqual(results[0].parent, results[1].parent)
            self.assertEqual(
                [b"page-1.png", b"page-2.png"],
                [path.read_bytes() for path in results],
            )


if __name__ == "__main__":
    unittest.main()
