import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.main import run_pipeline
from src.music_convert.musicxml_io import load_musicxml


class MainPipelinePageMergeTests(unittest.TestCase):
    fixtures = Path(__file__).parent / "fixtures"

    def run_pdf_pipeline(
        self,
        page_fixtures,
        expect_failure=False,
        *,
        root=None,
        document_name="two-pages.pdf",
        fail_midi=False,
        fail_render=False,
    ):
        temporary_directory = None
        if root is None:
            temporary_directory = tempfile.TemporaryDirectory()
            self.addCleanup(temporary_directory.cleanup)
            root = Path(temporary_directory.name)
        else:
            root = Path(root)
        pdf = root / document_name
        pdf.touch()
        out_dir = root / "published"
        images = [
            root / f"{pdf.stem}-page-1.png",
            root / f"{pdf.stem}-page-2.png",
        ]
        for image in images:
            image.touch()

        output_directories = []

        def recognize(image, output_directory, _config):
            index = len(output_directories)
            output_directory = Path(output_directory)
            output_directories.append(output_directory)
            output_directory.mkdir(parents=True, exist_ok=True)
            result = output_directory / f"{image.stem}.musicxml"
            fixture_bytes = (self.fixtures / page_fixtures[index]).read_bytes()
            fixture_bytes = fixture_bytes.replace(b'<tie type="start"/>', b"")
            fixture_bytes = fixture_bytes.replace(
                b'<notations><tied type="start"/><slur type="start" number="1"/></notations>',
                b"",
            )
            fixture_bytes = fixture_bytes.replace(
                b'<notations><slur type="stop" number="1"/></notations>', b""
            )
            result.write_bytes(fixture_bytes)
            return result

        def make_midi(source, destination, _options):
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            midi_content = (
                b"partial" if fail_midi else (source.source_musicxml or b"mock midi")
            )
            destination.write_bytes(midi_content)
            if fail_midi:
                raise RuntimeError("mock conversion failure")

        def make_jianpu(source, destination, **_kwargs):
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"mock text")

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("src.main.pdf_to_images", return_value=images))
        stack.enter_context(
            patch("src.main.preprocess_image", side_effect=lambda path, _dest: path)
        )
        stack.enter_context(patch("src.main.is_audiveris_available", return_value=True))
        stack.enter_context(patch("src.main.image_to_musicxml", side_effect=recognize))
        midi = stack.enter_context(
            patch("src.main.core.score_model_to_midi", side_effect=make_midi)
        )
        jianpu = stack.enter_context(
            patch("src.main.score_model_to_jianpu_text_file", side_effect=make_jianpu)
        )
        stack.enter_context(
            patch(
                "src.main.render_jianpu_pdf",
                side_effect=lambda _model, destination, **_kwargs: make_jianpu(
                    None, destination
                ),
            )
        )
        if fail_render:
            stack.enter_context(
                patch(
                    "src.main.musicxml_to_png",
                    side_effect=RuntimeError("mock render failure"),
                )
            )
        if expect_failure:
            with self.assertRaises(ValueError):
                run_pipeline(pdf, out_dir)
            results = []
        elif fail_midi:
            with self.assertRaisesRegex(RuntimeError, "mock conversion failure"):
                run_pipeline(pdf, out_dir)
            results = []
        elif fail_render:
            with self.assertRaisesRegex(RuntimeError, "mock render failure"):
                run_pipeline(pdf, out_dir, render_png=True)
            results = []
        else:
            results = run_pipeline(pdf, out_dir)
        return results, output_directories, midi, jianpu, out_dir

    def run_root(self, result):
        return result.musicxml.parent.parent

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
        run_dir = self.run_root(results[0])
        self.assertEqual(
            [Path("musicxml/pages/page-0001"), Path("musicxml/pages/page-0002")],
            [
                path.relative_to(output_directories[0].parents[2])
                for path in output_directories
            ],
        )
        self.assertEqual(out_dir, run_dir.parent)
        self.assertEqual(run_dir / "musicxml" / "merged.musicxml", results[0].musicxml)
        self.assertTrue(
            all(
                path.is_relative_to(run_dir)
                for path in (
                    results[0].musicxml,
                    results[0].midi,
                    results[0].jianpu_txt,
                )
            )
        )
        merged = load_musicxml(results[0].musicxml)
        self.assertEqual(5, len(merged.parts))
        self.assertEqual(
            ["P-S", "P-A", "P-T", "P-BR", "P-B"],
            [part.id for part in merged.parts],
        )
        self.assertEqual([0, 1], [measure.index for measure in merged.measures])
        self.assertTrue(all(len(part.events) == 2 for part in merged.parts))

    def test_distinct_documents_publish_distinct_paths_and_preserve_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_results, _, _, _, _ = self.run_pdf_pipeline(
                ("omr-page-1.musicxml", "omr-page-2.musicxml"),
                root=root,
                document_name="first.pdf",
            )
            first = first_results[0]
            first_root = self.run_root(first)
            first_content = {
                path.relative_to(first_root): path.read_bytes()
                for path in first_root.rglob("*")
                if path.is_file()
            }
            second_results, _, _, _, _ = self.run_pdf_pipeline(
                ("omr-page-2.musicxml", "omr-page-1.musicxml"),
                root=root,
                document_name="second.pdf",
            )
            second = second_results[0]

            self.assertNotEqual(first_root, self.run_root(second))
            self.assertNotEqual(first.musicxml, second.musicxml)
            self.assertNotEqual(first.midi, second.midi)
            self.assertTrue(
                all(
                    path.read_bytes() == content
                    for relative, content in first_content.items()
                    for path in [first_root / relative]
                )
            )
            self.assertNotEqual(
                first.musicxml.read_bytes(), second.musicxml.read_bytes()
            )
            self.assertNotEqual(first.midi.read_bytes(), second.midi.read_bytes())

    def test_failed_conversion_publishes_nothing_and_preserves_previous_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            successful, _, _, _, output_root = self.run_pdf_pipeline(
                ("omr-page-1.musicxml", "omr-page-2.musicxml"),
                root=root,
                document_name="repeated.pdf",
            )
            previous = successful[0]
            previous_root = self.run_root(previous)
            previous_content = {
                path.relative_to(previous_root): path.read_bytes()
                for path in previous_root.rglob("*")
                if path.is_file()
            }
            published_before = {path for path in output_root.iterdir() if path.is_dir()}

            self.run_pdf_pipeline(
                ("omr-page-2.musicxml", "omr-page-1.musicxml"),
                root=root,
                document_name="repeated.pdf",
                fail_midi=True,
            )

            self.assertEqual(
                published_before,
                {path for path in output_root.iterdir() if path.is_dir()},
            )
            self.assertEqual([], list(output_root.glob(".staging-*")))
            self.assertEqual(
                previous_content,
                {
                    path.relative_to(previous_root): path.read_bytes()
                    for path in previous_root.rglob("*")
                    if path.is_file()
                },
            )

    def test_render_failure_publishes_nothing_and_preserves_previous_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            successful, _, _, _, output_root = self.run_pdf_pipeline(
                ("omr-page-1.musicxml", "omr-page-2.musicxml"),
                root=root,
                document_name="rendered.pdf",
            )
            previous_root = self.run_root(successful[0])
            previous_content = {
                path.relative_to(previous_root): path.read_bytes()
                for path in previous_root.rglob("*")
                if path.is_file()
            }
            published_before = {path for path in output_root.iterdir() if path.is_dir()}

            self.run_pdf_pipeline(
                ("omr-page-2.musicxml", "omr-page-1.musicxml"),
                root=root,
                document_name="rendered.pdf",
                fail_render=True,
            )

            self.assertEqual(
                published_before,
                {path for path in output_root.iterdir() if path.is_dir()},
            )
            self.assertEqual([], list(output_root.glob(".staging-*")))
            self.assertEqual(
                previous_content,
                {
                    path.relative_to(previous_root): path.read_bytes()
                    for path in previous_root.rglob("*")
                    if path.is_file()
                },
            )

    def test_renamed_page_part_fails_before_conversion_or_merged_output(self):
        _results, _directories, midi, jianpu, out_dir = self.run_pdf_pipeline(
            ("omr-page-1.musicxml", "omr-page-2-renamed-part.musicxml"),
            expect_failure=True,
        )
        self.assertEqual(0, midi.call_count)
        self.assertEqual(0, jianpu.call_count)
        self.assertEqual([], [path for path in out_dir.iterdir() if path.is_dir()])

    def test_omitted_page_part_fails_before_conversion_or_merged_output(self):
        _results, _directories, midi, jianpu, out_dir = self.run_pdf_pipeline(
            ("omr-page-1.musicxml", "omr-page-2-omitted-part.musicxml"),
            expect_failure=True,
        )
        self.assertEqual(0, midi.call_count)
        self.assertEqual(0, jianpu.call_count)
        self.assertEqual([], [path for path in out_dir.iterdir() if path.is_dir()])

    def test_musicxml_input_does_not_invoke_omr_and_returns_one_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "score.musicxml"
            original = (self.fixtures / "satbb-two-measures.musicxml").read_bytes()
            source.write_bytes(original)
            with (
                patch("src.main.image_to_musicxml") as recognize,
                patch("src.main.core.score_model_to_midi") as midi,
                patch("src.main.score_model_to_jianpu_text_file") as jianpu,
                patch("src.main.render_jianpu_pdf"),
            ):
                results = run_pipeline(source, root / "output")
                self.assertEqual(1, len(results))
                self.assertNotEqual(source, results[0].musicxml)
                self.assertEqual(original, results[0].musicxml.read_bytes())
                self.assertEqual(original, source.read_bytes())
                self.assertTrue(results[0].midi.is_relative_to(root / "output"))
                recognize.assert_not_called()
                midi.assert_called_once()
                jianpu.assert_called_once()


if __name__ == "__main__":
    unittest.main()
