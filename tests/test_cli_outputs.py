import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.main import build_parser, main, run_pipeline
from src.music_convert.musicxml_io import load_musicxml
from src.music_convert.validation import validate_score

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"
SOURCE_PARTS = ["P-S", "P-A", "P-T", "P-BR", "P-B"]


def _write_output(path, content=b"mock output"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class CliOutputContractTests(unittest.TestCase):
    def test_parser_exposes_notation_and_format_options(self):
        args = build_parser().parse_args(["score.musicxml"])

        self.assertEqual("movable", args.mode)
        self.assertIsNone(args.tonic)
        self.assertEqual(("text", "pdf", "musicxml", "midi"), args.formats)

    def test_parser_rejects_unknown_output_formats(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["score.musicxml", "--formats", "image"])

    def test_musicxml_emits_one_complete_source_preserving_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "score.musicxml"
            original = (FIXTURES / "satbb-two-measures.musicxml").read_bytes()
            source.write_bytes(original)
            loaded = load_musicxml
            with (
                patch("src.main.load_musicxml", wraps=loaded) as parse,
                patch(
                    "src.main.core.score_model_to_midi",
                    side_effect=lambda _model, path, _options: _write_output(path),
                    create=True,
                ) as midi,
                patch(
                    "src.main.score_model_to_jianpu_text_file",
                    side_effect=lambda _model, path, **_kwargs: _write_output(path),
                    create=True,
                ) as text,
                patch(
                    "src.main.render_jianpu_pdf",
                    side_effect=lambda _model, path, **_kwargs: _write_output(path),
                    create=True,
                ) as pdf,
            ):
                results = run_pipeline(
                    source,
                    root / "output",
                    mode="fixed",
                    tonic="D",
                )

            self.assertEqual(1, len(results))
            result = results[0]
            for path in (
                result.musicxml,
                result.midi,
                result.jianpu_txt,
                result.jianpu_pdf,
            ):
                self.assertIsNotNone(path)
                self.assertTrue(path.is_file())
            self.assertEqual(original, result.musicxml.read_bytes())
            self.assertFalse(result.requires_review)
            self.assertIsNone(result.review_report)
            self.assertEqual(1, parse.call_count)
            self.assertEqual(
                SOURCE_PARTS, [part.id for part in load_musicxml(result.musicxml).parts]
            )
            self.assertEqual(1, midi.call_count)
            self.assertIs(midi.call_args.args[0], text.call_args.args[0])
            self.assertIs(text.call_args.args[0], pdf.call_args.args[0])
            self.assertEqual(1, text.call_count)
            self.assertEqual("fixed", text.call_args.kwargs["mode"])
            self.assertEqual("D", text.call_args.kwargs["tonic"])
            self.assertEqual(1, pdf.call_count)
            self.assertEqual("fixed", pdf.call_args.kwargs["notation"])
            self.assertEqual("D", pdf.call_args.kwargs["tonic"])

    def test_formats_emit_only_selected_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "score.musicxml"
            source.write_bytes((FIXTURES / "satbb-two-measures.musicxml").read_bytes())
            with (
                patch("src.main.core.score_model_to_midi", create=True) as midi,
                patch("src.main.score_model_to_jianpu_text_file", create=True) as text,
                patch("src.main.render_jianpu_pdf", create=True) as pdf,
            ):
                results = run_pipeline(source, root / "output", formats=("musicxml",))

            self.assertEqual(1, len(results))
            result = results[0]
            self.assertIsNotNone(result.musicxml)
            self.assertIsNone(result.midi)
            self.assertIsNone(result.jianpu_txt)
            self.assertIsNone(result.jianpu_pdf)
            self.assertIsNone(result.review_report)
            midi.assert_not_called()
            text.assert_not_called()
            pdf.assert_not_called()
            output_files = {
                path.name
                for path in result.musicxml.parent.parent.rglob("*")
                if path.is_file()
            }
            self.assertEqual({"score.musicxml"}, output_files)

    def test_keyless_movable_fails_closed_but_fixed_mode_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "keyless.musicxml"
            source.write_bytes(
                b"""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note></measure></part></score-partwise>"""
            )
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "missing_(tonic|key_mode)"):
                run_pipeline(source, output)

            self.assertEqual([], [path for path in output.iterdir() if path.is_dir()])
            with (
                patch(
                    "src.main.score_model_to_jianpu_text_file",
                    side_effect=lambda _model, path, **_kwargs: _write_output(path),
                    create=True,
                ),
                patch(
                    "src.main.render_jianpu_pdf",
                    side_effect=lambda _model, path, **_kwargs: _write_output(path),
                    create=True,
                ),
            ):
                results = run_pipeline(source, output, mode="fixed")

            self.assertEqual(1, len(results))
            self.assertTrue(results[0].jianpu_txt.is_file())
            self.assertTrue(results[0].jianpu_pdf.is_file())

    def test_missing_meter_fails_before_publishing_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = FIXTURES / "keyless-no-meter.musicxml"
            output = root / "output"
            parsed = load_musicxml(source)
            self.assertIsNone(parsed.measures[0].beats)
            self.assertEqual(4, parsed.measures[0].duration)

            with self.assertRaisesRegex(ValueError, "missing_meter"):
                run_pipeline(source, output, mode="fixed")

            self.assertEqual([], list(output.glob("*")))
            self.assertEqual([], list(output.glob(".staging-*")))

    def test_demo_honors_selected_pdf_and_fixed_notation_options(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            rendered = []

            def write_pdf(model, path, *, notation, tonic):
                rendered.append((model, notation, tonic))
                return _write_output(path, b"mock Jianpu PDF")

            with patch("src.main.render_jianpu_pdf", side_effect=write_pdf):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--demo",
                            "chord_progression",
                            "--out",
                            str(output),
                            "--formats",
                            "pdf",
                            "--mode",
                            "fixed",
                            "--tonic",
                            "D",
                        ]
                    ),
                )

            files = [path for path in output.rglob("*") if path.is_file()]
            self.assertEqual(["chord_progression_c.pdf"], [path.name for path in files])
            self.assertEqual(1, len(rendered))
            self.assertEqual("fixed", rendered[0][1])
            self.assertEqual("D", rendered[0][2])

    def test_grand_staff_demo_keeps_default_movable_tonic_unspecified(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            rendered = []

            def write_pdf(model, path, *, notation, tonic):
                rendered.append((notation, tonic))
                return _write_output(path)

            with patch("src.main.render_jianpu_pdf", side_effect=write_pdf):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--demo",
                            "grand_staff",
                            "--out",
                            str(output),
                            "--formats",
                            "pdf",
                        ]
                    ),
                )

            self.assertEqual([("movable", None)], rendered)
            files = [path.name for path in output.rglob("*") if path.is_file()]
            self.assertEqual(["grand_staff_c.pdf"], files)

    def test_grand_staff_demo_preserves_explicit_tonic_with_selected_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            rendered = []

            def write_pdf(model, path, *, notation, tonic):
                rendered.append((notation, tonic))
                return _write_output(path)

            with patch("src.main.render_jianpu_pdf", side_effect=write_pdf):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--demo",
                            "grand_staff",
                            "--out",
                            str(output),
                            "--formats",
                            "pdf",
                            "--tonic",
                            "D",
                        ]
                    ),
                )

            self.assertEqual([("movable", "D")], rendered)
            self.assertEqual(
                ["grand_staff_c.pdf"],
                [path.name for path in output.rglob("*") if path.is_file()],
            )

    def test_bach_prelude_pdf_demo_has_valid_four_four_measures_only(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            observed = []

            def write_pdf(model, path, *, notation, tonic):
                observed.append((model, notation, tonic))
                return _write_output(path)

            with patch("src.main.render_jianpu_pdf", side_effect=write_pdf):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--demo",
                            "bach_prelude",
                            "--out",
                            str(output),
                            "--formats",
                            "pdf",
                            "--mode",
                            "fixed",
                        ]
                    ),
                )

            self.assertEqual(1, len(observed))
            model, notation, _tonic = observed[0]
            self.assertEqual("fixed", notation)
            self.assertEqual([], validate_score(model))
            self.assertEqual(4, len(model.measures))
            left_hand = next(part for part in model.parts if "LH" in part.name)
            for measure_index in range(4):
                events = [
                    event
                    for event in left_hand.events
                    if event.measure_index == measure_index
                ]
                self.assertEqual([2, 2], [event.duration for event in events])
            self.assertEqual(
                ["bach_prelude_m1_m4.pdf"],
                [path.name for path in output.rglob("*") if path.is_file()],
            )

    def test_unresolved_omr_boundary_publishes_review_only_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unresolved.pdf"
            source.touch()
            page_images = [root / "page-1.png", root / "page-2.png"]
            for image in page_images:
                image.touch()

            def recognize(image, output_directory, _config):
                page_index = page_images.index(image)
                fixture_name = (
                    "omr-page-1.musicxml" if page_index == 0 else "omr-page-2.musicxml"
                )
                return _write_output(
                    Path(output_directory) / fixture_name,
                    (FIXTURES / fixture_name).read_bytes(),
                )

            with (
                patch("src.main.pdf_to_images", return_value=page_images),
                patch(
                    "src.main.preprocess_image", side_effect=lambda path, _dest: path
                ),
                patch("src.main.is_audiveris_available", return_value=True),
                patch("src.main.image_to_musicxml", side_effect=recognize),
                patch("src.main.core.score_model_to_midi") as midi,
                patch("src.main.score_model_to_jianpu_text_file") as text,
                patch("src.main.render_jianpu_pdf") as pdf,
            ):
                results = run_pipeline(source, root / "output")

            self.assertEqual(1, len(results))
            result = results[0]
            self.assertTrue(result.requires_review)
            self.assertEqual("review_only", result.publication_state)
            self.assertIsNone(result.musicxml)
            self.assertIsNone(result.midi)
            self.assertIsNone(result.jianpu_txt)
            self.assertIsNone(result.jianpu_pdf)
            midi.assert_not_called()
            text.assert_not_called()
            pdf.assert_not_called()
            self.assertTrue(result.review_report.is_file())
            report = json.loads(result.review_report.read_text(encoding="utf-8"))
            self.assertEqual("review_only", report["publication_state"])
            codes = {issue["code"] for issue in report["validation_issues"]}
            self.assertIn("tie_discontinuity", codes)
            self.assertIn("review_required", codes)
            self.assertIn("page_boundary_tie_unresolved", codes)
            located = [
                issue
                for issue in report["validation_issues"]
                if issue["code"] == "page_boundary_tie_unresolved"
            ]
            self.assertTrue(located)
            self.assertTrue(
                any(
                    issue["location"]["page"] == 1
                    and issue["location"]["measure_number"] == "8"
                    for issue in located
                )
            )
            self.assertEqual(
                {"review.json"},
                {
                    path.name
                    for path in result.review_report.parent.rglob("*")
                    if path.is_file()
                },
            )

    def test_two_page_omr_is_merged_once_and_always_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ensemble.pdf"
            source.touch()
            page_images = [root / "page-1.png", root / "page-2.png"]
            for image in page_images:
                image.touch()

            def recognize(image, output_directory, _config):
                page_index = page_images.index(image)
                fixture_name = (
                    "omr-page-1.musicxml" if page_index == 0 else "omr-page-2.musicxml"
                )
                fixture_bytes = (FIXTURES / fixture_name).read_bytes()
                fixture_bytes = fixture_bytes.replace(b'<tie type="start"/>', b"")
                fixture_bytes = fixture_bytes.replace(
                    b'<notations><tied type="start"/><slur type="start" number="1"/></notations>',
                    b"",
                )
                fixture_bytes = fixture_bytes.replace(
                    b'<notations><slur type="stop" number="1"/></notations>', b""
                )
                return _write_output(
                    Path(output_directory) / fixture_name, fixture_bytes
                )

            seen_models = []

            def write_text(model, path, **_kwargs):
                seen_models.append(model)
                return _write_output(path)

            with (
                patch("src.main.pdf_to_images", return_value=page_images),
                patch(
                    "src.main.preprocess_image", side_effect=lambda path, _dest: path
                ),
                patch("src.main.is_audiveris_available", return_value=True),
                patch("src.main.image_to_musicxml", side_effect=recognize),
                patch(
                    "src.main.core.musicxml_to_midi",
                    side_effect=lambda _source, path, _options: _write_output(path),
                ),
                patch(
                    "src.main.core.score_model_to_midi",
                    side_effect=lambda model, path, _options: _write_output(path),
                    create=True,
                ) as midi,
                patch(
                    "src.main.score_model_to_jianpu_text_file",
                    side_effect=write_text,
                    create=True,
                ) as text,
                patch(
                    "src.main.render_jianpu_pdf",
                    side_effect=lambda model, path, **_kwargs: _write_output(path),
                    create=True,
                ) as pdf,
            ):
                results = run_pipeline(source, root / "output")

            self.assertEqual(1, len(results))
            self.assertEqual(1, text.call_count)
            self.assertEqual(1, pdf.call_count)
            self.assertIs(midi.call_args.args[0], seen_models[0])
            self.assertIs(pdf.call_args.args[0], seen_models[0])
            self.assertEqual(2, len(seen_models[0].measures))
            self.assertEqual(SOURCE_PARTS, [part.id for part in seen_models[0].parts])
            result = results[0]
            self.assertTrue(result.requires_review)
            self.assertTrue(result.review_report.is_file())
            report = json.loads(result.review_report.read_text(encoding="utf-8"))
            self.assertEqual(str(source), report["input_path"])
            self.assertEqual(2, report["page_count"])
            self.assertEqual(
                ["Soprano", "Alto", "Tenor", "Baritone", "Bass"],
                report["source_part_names"],
            )
            self.assertEqual("needs_source_image_review", report["state"])
            self.assertEqual([], report["validation_issues"])
            self.assertIn(
                "review.json",
                {path.name for path in result.review_report.parent.iterdir()},
            )


if __name__ == "__main__":
    unittest.main()
