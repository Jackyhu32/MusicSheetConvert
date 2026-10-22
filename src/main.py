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
import logging
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
    write_score,
)
from .music_convert.musicxml_io import load_musicxml, merge_page_models
from .ocr import AudiverisConfig, image_to_musicxml, is_audiveris_available
from .preprocess import pdf_to_images, preprocess_image
from .render import (
    musicxml_to_jianpu_text_file,
    musicxml_to_png,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("music-sheet-convert")


@dataclass
class PipelineResult:
    """Result of a single pipeline run."""

    image: Path
    musicxml: Path | None = None
    midi: Path | None = None
    jianpu_txt: Path | None = None
    rendered_png: Path | None = None


def _run_pipeline_in_directory(
    input_path: Path,
    out_dir: Path,
    bpm: int = 90,
    render_png: bool = False,
    skip_ocr: bool = False,
    audiveris_cfg: AudiverisConfig | None = None,
) -> list[PipelineResult]:
    """Run the end-to-end pipeline. One ``PipelineResult`` is produced for the input document.

    Args:
        input_path: input file (PDF / PNG / JPG).
        out_dir:    output root directory. Subdirectories are created automatically.
        bpm:        default tempo for the generated MIDI.
        render_png: if ``True``, also render the staff-notation PNG via MuseScore.
        skip_ocr:   skip OCR (use when the input is already a MusicXML file).
        audiveris_cfg: Audiveris configuration.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    audiveris_cfg = audiveris_cfg or AudiverisConfig()

    suffix = input_path.suffix.lower()
    image_paths: list[Path] = []
    pre_dir = out_dir / "preprocessed"

    if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
        log.info("Preprocessing single image: %s", input_path)
        image_paths = [preprocess_image(input_path, pre_dir / input_path.name)]
    elif suffix == ".pdf":
        log.info("PDF -> images: %s", input_path)
        pages_dir = out_dir / "pages"
        pages = pdf_to_images(input_path, pages_dir)
        log.info("Got %d page(s), preprocessing each", len(pages))
        image_paths = [preprocess_image(p, pre_dir / p.name) for p in pages]
    elif suffix in (".xml", ".musicxml", ".mxl"):
        # Already MusicXML: skip OCR.
        skip_ocr = True
        image_paths = [input_path]
    else:
        raise ValueError(f"Unsupported input format: {suffix}")

    if skip_ocr:
        musicxml_path = image_paths[0]
        result_image = input_path
    else:
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
            page_musicxml = image_to_musicxml(
                image, page_output_dir, audiveris_cfg
            )
            page_models.append(load_musicxml(page_musicxml))

        merged_model = merge_page_models(page_models)
        if merged_model.source_musicxml is None:
            raise ValueError("merged score did not produce editable MusicXML")
        musicxml_path = out_dir / "musicxml" / "merged.musicxml"
        musicxml_path.parent.mkdir(parents=True, exist_ok=True)
        musicxml_path.write_bytes(merged_model.source_musicxml)
        result_image = input_path if suffix == ".pdf" else image_paths[0]

    result = PipelineResult(image=result_image, musicxml=musicxml_path)

    # Convert the complete source document once after all OMR pages validate.
    midi_out = out_dir / "midi" / f"{musicxml_path.stem}.mid"
    log.info("MusicXML -> MIDI: %s -> %s", musicxml_path, midi_out)
    core.musicxml_to_midi(musicxml_path, midi_out, core.ConvertOptions(bpm=bpm))
    result.midi = midi_out

    jianpu_out = out_dir / "jianpu" / f"{musicxml_path.stem}.txt"
    log.info("MusicXML -> jianpu text: %s", jianpu_out)
    musicxml_to_jianpu_text_file(musicxml_path, jianpu_out)
    result.jianpu_txt = jianpu_out

    if render_png:
        png_out = out_dir / "rendered" / f"{musicxml_path.stem}.png"
        log.info("MusicXML -> staff PNG: %s", png_out)
        musicxml_to_png(musicxml_path, png_out)
        result.rendered_png = png_out

    return [result]



def run_pipeline(
    input_path: Path,
    out_dir: Path,
    bpm: int = 90,
    render_png: bool = False,
    skip_ocr: bool = False,
    audiveris_cfg: AudiverisConfig | None = None,
) -> list[PipelineResult]:
    """Run a document pipeline transactionally and publish a unique bundle."""
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", input_path.stem).strip(".-")
    safe_stem = safe_stem or "document"
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".staging-{run_id}-", dir=out_dir)
    )
    final_dir = out_dir / f"{safe_stem}-{run_id}"

    try:
        results = _run_pipeline_in_directory(
            input_path=input_path,
            out_dir=staging_dir,
            bpm=bpm,
            render_png=render_png,
            skip_ocr=skip_ocr,
            audiveris_cfg=audiveris_cfg,
        )
        os.rename(staging_dir, final_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    for result in results:
        for attribute in ("image", "musicxml", "midi", "jianpu_txt", "rendered_png"):
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
    p.add_argument("input", type=Path, nargs="?", default=None,
                   help="Input file (PDF/PNG/JPG/MusicXML). Omit when using --demo.")
    p.add_argument("--out", type=Path, default=Path("./data/output"),
                   help="Output root directory")
    p.add_argument("--bpm", type=int, default=90, help="Default MIDI tempo")
    p.add_argument("--render", action="store_true",
                   help="Additionally render staff-notation PNG via MuseScore")
    p.add_argument("--skip-ocr", action="store_true",
                   help="Skip OCR (use when the input is already a MusicXML file)")
    p.add_argument("--audiveris-bin", type=str, default=None,
                   help="Path to the Audiveris executable")

    # Built-in complex-score generators.
    p.add_argument("--demo", choices=["grand_staff", "chord_progression",
                                      "key_demonstration", "bach_prelude"],
                   help="Generate a preset complex score instead of reading a file")
    p.add_argument("--key", type=str, default="C",
                   choices=list(KEY_PRESETS.keys()),
                   help="Key signature for the generated score")
    p.add_argument("--title", type=str, default=None,
                   help="Title for the generated score")
    return p


def run_demo(demo: str, key_name: str, title: str | None,
             out_dir: Path, bpm: int, render: bool) -> PipelineResult:
    """Generate a preset complex score and emit the full output bundle (MusicXML / MIDI / jianpu / PNG)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("Generating complex score: demo=%s, key=%s, title=%s",
             demo, key_name, title)

    if demo == "grand_staff":
        # Use the selected key's one-octave scale on the right hand.
        from music21 import pitch as m21pitch
        tonic = KEY_PRESETS[key_name].tonic
        # tonic.name + octave (B- etc. are also supported).
        tonic_oct4 = m21pitch.Pitch(tonic.nameWithOctave)
        scale_steps = [0, 2, 4, 5, 7, 9, 11, 12]   # major scale (white keys)
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
            chord_root = m21pitch.Pitch(tonic.nameWithOctave).transpose(-12)  # down an octave
            third = chord_root.transpose(4)
            fifth = chord_root.transpose(7)
            lh.append([
                NoteSpec([chord_root.nameWithOctave,
                          third.nameWithOctave,
                          fifth.nameWithOctave], 4.0),
            ])
        score = build_grand_staff(
            rh, lh,
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
            chords, key_name=key_name,
            title=title or f"Chord Progression in {key_name}",
        )
        base_name = f"chord_progression_{key_name.lower()}"
    elif demo == "bach_prelude":
        score = build_bach_prelude_c_major()
        base_name = "bach_prelude_m1_m4"
    else:  # key_demonstration
        score = build_key_demonstration()
        base_name = "key_demonstration"

    paths = write_score(score, out_dir, base_name)
    log.info("MusicXML: %s", paths["musicxml"])
    log.info("MIDI    : %s", paths["midi"])

    result = PipelineResult(
        image=paths["musicxml"],
        musicxml=paths["musicxml"],
        midi=paths["midi"],
    )

    # jianpu
    jianpu_out = out_dir / "jianpu" / f"{base_name}.txt"
    musicxml_to_jianpu_text_file(paths["musicxml"], jianpu_out)
    result.jianpu_txt = jianpu_out
    log.info("jianpu text: %s", jianpu_out)

    # Render PNG
    if render:
        png_out = out_dir / "rendered" / f"{base_name}.png"
        try:
            musicxml_to_png(paths["musicxml"], png_out)
            result.rendered_png = png_out
            log.info("Rendered staff PNG: %s", png_out)
        except RuntimeError as e:
            log.warning("MuseScore unavailable, skipping render: %s", e)
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.demo:
        result = run_demo(
            demo=args.demo, key_name=args.key, title=args.title,
            out_dir=args.out, bpm=args.bpm, render=args.render,
        )
        print("\n=== Complex score generation result ===")
        print(f"MusicXML : {result.musicxml}")
        print(f"MIDI     : {result.midi}")
        print(f"jianpu   : {result.jianpu_txt}")
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
    )
    print("\n=== Pipeline results ===")
    for r in results:
        print(f"Image    : {r.image}")
        print(f"MusicXML : {r.musicxml}")
        print(f"MIDI     : {r.midi}")
        print(f"jianpu   : {r.jianpu_txt}")
        if r.rendered_png:
            print(f"PNG      : {r.rendered_png}")
        print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
