"""End-to-end pipeline: image/PDF -> OCR -> MusicXML -> MIDI -> jianpu / staff rendering.

CLI usage:
    # Image / PDF input
    python -m src.main input.png --out ./data/output --bpm 100
    python -m src.main score.pdf --out ./data/output --skip-ocr

    # Built-in complex-score generators (no input file required)
    python -m src.main --demo grand_staff --key G --out ./data/output
    python -m src.main --demo chord_progression --key C --out ./data/output
    python -m src.main --demo key_demonstration --out ./data/output
    python -m src.main --demo bach_prelude --render --out ./data/output
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .music_convert import core
from .music_convert.advanced import (
    KEY_PRESETS,
    NoteSpec,
    build_bach_prelude_c_major,
    build_chord_progression,
    build_grand_staff,
    build_key_demonstration,
)
from .music_convert.musicxml_io import load_musicxml, merge_page_models
from .music_convert.validation import validate_score
from .ocr import AudiverisConfig, image_to_musicxml, is_audiveris_available
from .preprocess import pdf_to_images, preprocess_image
from .render import (
    musicxml_to_png,
    score_model_to_jianpu_text_file,
)
from .render.jianpu_pdf import render_jianpu_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("music-sheet-convert")


_DEFAULT_FORMATS = ("text", "pdf", "musicxml", "midi")
_SUPPORTED_FORMATS = frozenset(_DEFAULT_FORMATS)


def _parse_formats(value: str) -> tuple[str, ...]:
    formats = tuple(item.strip().lower() for item in value.split(","))
    if not formats or any(not item for item in formats):
        raise argparse.ArgumentTypeError("formats must be a comma-separated list")
    unknown = [item for item in formats if item not in _SUPPORTED_FORMATS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported format(s): {', '.join(unknown)}")
    if len(set(formats)) != len(formats):
        raise argparse.ArgumentTypeError("formats must not contain duplicates")
    return formats


def _normalize_formats(formats: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(formats, str):
        try:
            return _parse_formats(formats)
        except argparse.ArgumentTypeError as error:
            raise ValueError(str(error)) from error
    values = tuple(str(item).strip().lower() for item in formats)
    if not values or any(not item for item in values):
        raise ValueError("formats must contain at least one supported format")
    unknown = [item for item in values if item not in _SUPPORTED_FORMATS]
    if unknown:
        raise ValueError(f"unsupported format(s): {', '.join(unknown)}")
    if len(set(values)) != len(values):
        raise ValueError("formats must not contain duplicates")
    return values


@dataclass
class PipelineResult:
    """Result of a single document pipeline run."""

    image: Path
    musicxml: Path | None = None
    midi: Path | None = None
    jianpu_txt: Path | None = None
    rendered_png: Path | None = None
    jianpu_pdf: Path | None = None
    review_report: Path | None = None
    requires_review: bool = False
    publication_state: str = "complete"


def _write_review_report(
    out_dir: Path,
    input_path: Path,
    page_count: int,
    model,
    issues,
    *,
    publication_state: str,
    missing_meter: tuple[tuple[int, str], ...] = (),
) -> Path:
    issue_rows = []
    for issue in issues:
        location = issue.location
        issue_rows.append(
            {
                "code": issue.code,
                "part_id": issue.part_id,
                "measure_number": issue.measure_number,
                "message": issue.message,
                "location": (
                    {
                        "page": location.page,
                        "system": location.system,
                        "measure_number": location.measure_number,
                    }
                    if location is not None
                    else None
                ),
            }
        )
    for review in model.review_issues:
        location = review.location
        issue_rows.append(
            {
                "code": review.code,
                "part_id": None,
                "measure_number": location.measure_number if location else None,
                "message": review.message,
                "location": (
                    {
                        "page": location.page,
                        "system": location.system,
                        "measure_number": location.measure_number,
                    }
                    if location is not None
                    else None
                ),
                "candidates": [str(candidate) for candidate in review.candidates],
                "confidence": (
                    review.confidence
                    if review.confidence is None or math.isfinite(review.confidence)
                    else None
                ),
            }
        )
    for measure_index, measure_number in missing_meter:
        event_location = next(
            (
                event.source_location
                for part in model.parts
                for event in part.events
                if event.measure_index == measure_index and event.source_location
            ),
            None,
        )
        issue_rows.append(
            {
                "code": "missing_meter",
                "part_id": None,
                "measure_number": measure_number,
                "message": f"No explicit or inherited meter for measure {measure_number}.",
                "location": (
                    {
                        "page": event_location.page,
                        "system": event_location.system,
                        "measure_number": event_location.measure_number,
                    }
                    if event_location is not None
                    else None
                ),
            }
        )

    report_path = out_dir / "review.json"
    report_path.write_text(
        json.dumps(
            {
                "input_path": str(input_path),
                "page_count": page_count,
                "source_part_names": [part.name for part in model.parts],
                "validation_issues": issue_rows,
                "state": "needs_source_image_review",
                "publication_state": publication_state,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report_path


def _run_pipeline_in_directory(
    input_path: Path,
    out_dir: Path,
    bpm: int = 90,
    render_png: bool = False,
    skip_ocr: bool = False,
    audiveris_cfg: AudiverisConfig | None = None,
    mode: str = "movable",
    tonic: str | None = None,
    formats: tuple[str, ...] = _DEFAULT_FORMATS,
) -> list[PipelineResult]:
    """Convert one input document from a single validated score model."""
    out_dir.mkdir(parents=True, exist_ok=True)
    audiveris_cfg = audiveris_cfg or AudiverisConfig()
    selected = _normalize_formats(formats)

    suffix = input_path.suffix.lower()
    is_omr = suffix not in (".xml", ".musicxml", ".mxl")
    page_count = 1
    result_image = input_path
    source_musicxml_path: Path | None = None

    if not is_omr:
        model = load_musicxml(input_path)
        source_musicxml_path = input_path
    else:
        pre_dir = out_dir / "preprocessed"
        rasterized_pages_dir: Path | None = None
        if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
            log.info("Preprocessing single image: %s", input_path)
            image_paths = [preprocess_image(input_path, pre_dir / input_path.name)]
        elif suffix == ".pdf":
            log.info("PDF -> images: %s", input_path)
            pages_dir = out_dir / "pages"
            rasterized_pages_dir = pages_dir
            pages = pdf_to_images(input_path, pages_dir)
            page_count = len(pages)
            log.info("Got %d page(s), preprocessing each", page_count)
            image_paths = [
                preprocess_image(page, pre_dir / page.name) for page in pages
            ]
        else:
            raise ValueError(f"Unsupported input format: {suffix}")

        if skip_ocr:
            raise ValueError("--skip-ocr requires a MusicXML input file")
        if not is_audiveris_available(audiveris_cfg):
            raise RuntimeError(
                "Audiveris not detected. Install it and put it on PATH, "
                "or pass a MusicXML file directly (--skip-ocr)."
            )

        page_models = []
        pages_output_dir = out_dir / "musicxml" / "pages"
        for page_number, image in enumerate(image_paths, start=1):
            page_output_dir = pages_output_dir / f"page-{page_number:04d}"
            log.info("Audiveris recognition: %s", image)
            page_musicxml = image_to_musicxml(image, page_output_dir, audiveris_cfg)
            page_models.append(load_musicxml(page_musicxml))
        model = merge_page_models(page_models)
        for intermediate_dir in (pre_dir, rasterized_pages_dir, pages_output_dir):
            if intermediate_dir is not None:
                shutil.rmtree(intermediate_dir, ignore_errors=True)
        try:
            (out_dir / "musicxml").rmdir()
        except OSError:
            pass

    if mode not in ("movable", "fixed"):
        raise ValueError("mode must be 'movable' or 'fixed'")
    missing_meter = tuple(
        (measure.index, measure.number)
        for measure in model.measures
        if measure.beats is None or measure.beat_type is None
    )
    issues = validate_score(model)
    if is_omr and (missing_meter or issues):
        result = PipelineResult(
            image=result_image,
            requires_review=True,
            publication_state="review_only",
        )
        result.review_report = _write_review_report(
            out_dir,
            input_path,
            page_count,
            model,
            issues,
            publication_state=result.publication_state,
            missing_meter=missing_meter,
        )
        return [result]

    if missing_meter:
        numbers = ", ".join(number for _index, number in missing_meter)
        raise ValueError(
            f"missing_meter: no explicit or inherited meter for measure(s) {numbers}"
        )
    if issues:
        codes = ", ".join(dict.fromkeys(issue.code for issue in issues))
        raise ValueError(f"score validation failed: {codes}")
    if not model.parts:
        raise ValueError("score has no source parts")

    result = PipelineResult(
        image=result_image,
        requires_review=(is_omr or model.requires_review or bool(model.review_issues)),
    )
    base_name = "merged" if is_omr else input_path.stem

    if "musicxml" in selected:
        if is_omr:
            if model.source_musicxml is None:
                raise ValueError("merged score did not produce editable MusicXML")
            musicxml_out = out_dir / "musicxml" / "merged.musicxml"
            musicxml_bytes = model.source_musicxml
        else:
            musicxml_out = out_dir / "musicxml" / f"{input_path.stem}{suffix}"
            musicxml_bytes = model.source_musicxml
            if musicxml_bytes is None:
                raise ValueError("source MusicXML bytes were not retained")
        musicxml_out.parent.mkdir(parents=True, exist_ok=True)
        musicxml_out.write_bytes(musicxml_bytes)
        result.musicxml = musicxml_out

    if "midi" in selected:
        midi_out = out_dir / "midi" / f"{base_name}.mid"
        log.info("ScoreModel -> MIDI: %s", midi_out)
        core.score_model_to_midi(model, midi_out, core.ConvertOptions(bpm=bpm))
        result.midi = midi_out

    if "text" in selected:
        jianpu_out = out_dir / "jianpu" / f"{base_name}.txt"
        log.info("ScoreModel -> Jianpu JSONL: %s", jianpu_out)
        score_model_to_jianpu_text_file(model, jianpu_out, mode=mode, tonic=tonic)
        result.jianpu_txt = jianpu_out

    if "pdf" in selected:
        jianpu_pdf = out_dir / "jianpu" / f"{base_name}.pdf"
        log.info("ScoreModel -> Jianpu PDF: %s", jianpu_pdf)
        render_jianpu_pdf(model, jianpu_pdf, notation=mode, tonic=tonic)
        result.jianpu_pdf = jianpu_pdf

    if result.requires_review:
        result.review_report = _write_review_report(
            out_dir,
            input_path,
            page_count,
            model,
            issues,
            publication_state=result.publication_state,
        )

    if render_png:
        png_out = out_dir / "rendered" / f"{base_name}.png"
        log.info("ScoreModel -> staff PNG: %s", png_out)
        render_source = result.musicxml or source_musicxml_path
        temporary_source: Path | None = None
        if render_source is None:
            if model.source_musicxml is None:
                raise ValueError(
                    "score has no editable MusicXML source for staff rendering"
                )
            temporary_source = out_dir / ".staff-render-source.musicxml"
            temporary_source.write_bytes(model.source_musicxml)
            render_source = temporary_source
        try:
            musicxml_to_png(render_source, png_out)
        finally:
            if temporary_source is not None:
                temporary_source.unlink(missing_ok=True)
        result.rendered_png = png_out

    return [result]


def run_pipeline(
    input_path: Path,
    out_dir: Path,
    bpm: int = 90,
    render_png: bool = False,
    skip_ocr: bool = False,
    audiveris_cfg: AudiverisConfig | None = None,
    mode: str = "movable",
    tonic: str | None = None,
    formats: str | tuple[str, ...] | list[str] = _DEFAULT_FORMATS,
) -> list[PipelineResult]:
    """Run a document pipeline transactionally and publish a unique bundle."""
    selected_formats = _normalize_formats(formats)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", input_path.stem).strip(".-")
    safe_stem = safe_stem or "document"
    staging_dir = Path(tempfile.mkdtemp(prefix=f".staging-{run_id}-", dir=out_dir))
    final_dir = out_dir / f"{safe_stem}-{run_id}"

    try:
        results = _run_pipeline_in_directory(
            input_path=input_path,
            out_dir=staging_dir,
            bpm=bpm,
            render_png=render_png,
            skip_ocr=skip_ocr,
            audiveris_cfg=audiveris_cfg,
            mode=mode,
            tonic=tonic,
            formats=selected_formats,
        )
        os.rename(staging_dir, final_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    for result in results:
        for attribute in (
            "image",
            "musicxml",
            "midi",
            "jianpu_txt",
            "rendered_png",
            "jianpu_pdf",
            "review_report",
        ):
            value = getattr(result, attribute)
            if value is None:
                continue
            try:
                relative_path = value.relative_to(staging_dir)
            except ValueError:
                continue
            setattr(result, attribute, final_dir / relative_path)
    return results


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Staff-notation / jianpu / MIDI / MusicXML conversion pipeline"
    )
    p.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help="Input file (PDF/PNG/JPG/MusicXML). Omit when using --demo.",
    )
    p.add_argument(
        "--out", type=Path, default=Path("./data/output"), help="Output root directory"
    )
    p.add_argument("--bpm", type=int, default=90, help="Default MIDI tempo")
    p.add_argument(
        "--render",
        action="store_true",
        help="Additionally render staff-notation PNG via MuseScore",
    )
    p.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip OCR (use when the input is already a MusicXML file)",
    )
    p.add_argument(
        "--audiveris-bin",
        type=str,
        default=None,
        help="Path to the Audiveris executable",
    )
    p.add_argument(
        "--mode",
        choices=("movable", "fixed"),
        default="movable",
        help="Jianpu notation mode (key mode remains in the source score)",
    )
    p.add_argument(
        "--tonic",
        type=str,
        default=None,
        help="Explicit Jianpu tonic, such as C, F#, or Bb",
    )
    p.add_argument(
        "--formats",
        type=_parse_formats,
        default=_DEFAULT_FORMATS,
        metavar="text,pdf,musicxml,midi",
        help="Comma-separated output formats",
    )

    # Built-in complex-score generators.
    p.add_argument(
        "--demo",
        choices=[
            "grand_staff",
            "chord_progression",
            "key_demonstration",
            "bach_prelude",
        ],
        help="Generate a preset complex score instead of reading a file",
    )
    p.add_argument(
        "--key",
        type=str,
        default="C",
        choices=list(KEY_PRESETS.keys()),
        help="Key signature for the generated score",
    )
    p.add_argument(
        "--title", type=str, default=None, help="Title for the generated score"
    )
    return p


def run_demo(
    demo: str,
    key_name: str,
    title: str | None,
    out_dir: Path,
    bpm: int,
    render: bool,
    mode: str = "movable",
    tonic: str | None = None,
    formats: tuple[str, ...] = _DEFAULT_FORMATS,
) -> PipelineResult:
    """Generate a preset score through the validated transactional bundle pipeline."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "Generating complex score: demo=%s, key=%s, title=%s", demo, key_name, title
    )

    if demo == "grand_staff":
        # Use the selected key's one-octave scale on the right hand.
        from music21 import pitch as m21pitch

        generated_tonic = KEY_PRESETS[key_name].tonic
        # tonic.name + octave (B- etc. are also supported).
        tonic_oct4 = m21pitch.Pitch(generated_tonic.nameWithOctave)
        scale_steps = [0, 2, 4, 5, 7, 9, 11, 12]  # major scale (white keys)
        rh = []
        for i in range(0, 8, 4):
            row = []
            for j in range(4):
                p = tonic_oct4.transpose(scale_steps[i + j])
                row.append(NoteSpec([p.nameWithOctave], 1.0))
            rh.append(row)
        # Left hand: a I chord per measure (tonic + third + fifth).
        lh = []
        for _ in range(2):
            chord_root = m21pitch.Pitch(generated_tonic.nameWithOctave).transpose(
                -12
            )  # down an octave
            third = chord_root.transpose(4)
            fifth = chord_root.transpose(7)
            lh.append(
                [
                    NoteSpec(
                        [
                            chord_root.nameWithOctave,
                            third.nameWithOctave,
                            fifth.nameWithOctave,
                        ],
                        4.0,
                    ),
                ]
            )
        score = build_grand_staff(
            rh,
            lh,
            key_name=key_name,
            title=title or f"Grand Staff in {key_name}",
        )
        base_name = f"grand_staff_{key_name.lower()}"
    elif demo == "chord_progression":
        # ii-V-I 7th chords: major keys use the C spelling, minor keys use A.
        if key_name in ("Am", "Em", "Dm"):
            chords = [
                ["A3", "C4", "E4", "G4"],
                ["B3", "D4", "F4", "A4"],
                ["E3", "G3", "B3", "D4"],
                ["A3", "C4", "E4", "G4"],
            ]
        else:
            chords = [
                ["D4", "F4", "A4", "C5"],
                ["G3", "B3", "D4", "F4"],
                ["C4", "E4", "G4", "B4"],
                ["C4", "E4", "G4", "B4"],
            ]
        score = build_chord_progression(
            chords,
            key_name=key_name,
            title=title or f"Chord Progression in {key_name}",
        )
        base_name = f"chord_progression_{key_name.lower()}"
    elif demo == "bach_prelude":
        score = build_bach_prelude_c_major()
        if title is not None:
            score.metadata.title = title
        base_name = "bach_prelude_m1_m4"
    else:  # key_demonstration
        score = build_key_demonstration()
        if title is not None:
            score.metadata.title = title
        base_name = "key_demonstration"

    with tempfile.TemporaryDirectory(prefix="score-demo-") as directory:
        source_musicxml = Path(directory) / f"{base_name}.musicxml"
        score.write("musicxml", fp=str(source_musicxml))
        results = run_pipeline(
            input_path=source_musicxml,
            out_dir=out_dir,
            bpm=bpm,
            render_png=render,
            skip_ocr=True,
            mode=mode,
            tonic=tonic,
            formats=formats,
        )

    result = results[0]
    result.image = next(
        path
        for path in (
            result.musicxml,
            result.jianpu_pdf,
            result.jianpu_txt,
            result.midi,
            result.rendered_png,
        )
        if path is not None
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.demo:
        result = run_demo(
            demo=args.demo,
            key_name=args.key,
            title=args.title,
            out_dir=args.out,
            bpm=args.bpm,
            render=args.render,
            mode=args.mode,
            tonic=args.tonic,
            formats=args.formats,
        )
        print("\n=== Complex score generation result ===")
        print(f"MusicXML : {result.musicxml}")
        print(f"MIDI     : {result.midi}")
        print(f"jianpu   : {result.jianpu_txt}")
        print(f"Jianpu PDF: {result.jianpu_pdf}")
        print(f"Review   : {result.review_report}")
        print(f"Status   : {result.publication_state}")
        if result.rendered_png:
            print(f"PNG      : {result.rendered_png}")
        return 0
    if not args.input:
        print("Error: provide an input file, or use --demo to generate a preset score")
        return 1
    cfg = AudiverisConfig(bin_path=args.audiveris_bin)
    results = run_pipeline(
        input_path=args.input,
        out_dir=args.out,
        bpm=args.bpm,
        render_png=args.render,
        skip_ocr=args.skip_ocr,
        audiveris_cfg=cfg,
        mode=args.mode,
        tonic=args.tonic,
        formats=args.formats,
    )
    print("\n=== Pipeline results ===")
    for r in results:
        print(f"Image    : {r.image}")
        print(f"MusicXML : {r.musicxml}")
        print(f"MIDI     : {r.midi}")
        print(f"jianpu   : {r.jianpu_txt}")
        print(f"Jianpu PDF: {r.jianpu_pdf}")
        print(f"Review   : {r.review_report}")
        print(f"Requires review: {r.requires_review}")
        print(f"Status   : {r.publication_state}")
        if r.rendered_png:
            print(f"PNG      : {r.rendered_png}")
        print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
