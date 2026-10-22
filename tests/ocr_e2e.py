"""OCR end-to-end tests using a MusicXML source built in a temporary directory."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.music_convert.advanced import NoteSpec, build_grand_staff
from src.ocr import (
    AudiverisConfig,
    find_audiveris,
    image_to_musicxml,
    is_audiveris_available,
)
from src.render import find_musescore

_JIANPU_PITCH_TOKEN = re.compile(r"(?:#+|b+)?[1-7](?:\^[1-9]\d*|v[1-9]\d*)?")
_PART_FIELDS = {"type", "part", "name"}
_EVENT_FIELDS = {
    "type",
    "part",
    "measure",
    "staff",
    "voice",
    "onset",
    "duration",
    "kind",
    "pitches",
    "written_pitches",
    "ties",
    "lyrics",
    "grace",
}
_EVENT_STRING_FIELDS = {
    "part",
    "measure",
    "staff",
    "voice",
    "onset",
    "duration",
}


def _reject_nonstandard_json_constant(constant: str) -> None:
    raise ValueError(f"Non-standard JSON constant {constant!r}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _validate_jianpu_jsonl(text: str) -> None:
    """Require core-schema JSONL rows and valid pitches for pitched events."""
    event_count = 0
    pitched_event_count = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(
                line,
                parse_constant=_reject_nonstandard_json_constant,
                object_pairs_hook=_unique_object,
            )
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid Jianpu JSONL on line {line_number}: {error}") from error
        if not isinstance(row, dict):
            raise TypeError(f"Jianpu JSONL line {line_number} must be an object")

        row_type = row.get("type")
        if row_type == "part":
            missing = _PART_FIELDS - row.keys()
            if missing:
                raise ValueError(
                    f"Jianpu part row on line {line_number} is missing field {min(missing)!r}"
                )
            if not all(isinstance(row[field], str) for field in ("type", "part", "name")):
                raise ValueError(
                    f"Jianpu part row on line {line_number} requires string type, part, and name fields"
                )
            continue
        if row_type != "event":
            raise ValueError(
                f"Unknown Jianpu JSONL row type on line {line_number}: {row_type!r}"
            )

        event_count += 1
        missing = _EVENT_FIELDS - row.keys()
        if missing:
            raise ValueError(
                f"Jianpu event row on line {line_number} is missing field {min(missing)!r}"
            )
        if not all(isinstance(row[field], str) for field in _EVENT_STRING_FIELDS):
            raise ValueError(
                f"Jianpu event row on line {line_number} has invalid string schema fields"
            )
        if not isinstance(row["written_pitches"], list) or not all(
            isinstance(pitch, str) for pitch in row["written_pitches"]
        ):
            raise ValueError(
                f"Jianpu event row on line {line_number} has invalid written_pitches"
            )
        if not isinstance(row["ties"], list) or not all(
            isinstance(tie, str) for tie in row["ties"]
        ):
            raise ValueError(f"Jianpu event row on line {line_number} has invalid ties")
        if not isinstance(row["lyrics"], list):
            raise TypeError(f"Jianpu event row on line {line_number} has invalid lyrics")
        if not isinstance(row["grace"], bool):
            raise TypeError(f"Jianpu event row on line {line_number} has invalid grace")

        kind = row["kind"]
        pitches = row["pitches"]
        if kind == "rest":
            if pitches != "0":
                raise ValueError(
                    f"Jianpu rest event on line {line_number} must have pitches exactly '0'"
                )
            continue
        if kind == "note":
            if not isinstance(pitches, str) or not _JIANPU_PITCH_TOKEN.fullmatch(pitches):
                raise ValueError(
                    f"Jianpu note event on line {line_number} must have one valid pitch token"
                )
        elif kind == "chord":
            if (
                not isinstance(pitches, list)
                or not pitches
                or any(
                    not isinstance(token, str)
                    or not _JIANPU_PITCH_TOKEN.fullmatch(token)
                    for token in pitches
                )
            ):
                raise ValueError(
                    f"Jianpu chord event on line {line_number} must have a non-empty list of valid pitch tokens"
                )
        else:
            raise ValueError(
                f"Unknown Jianpu event kind on line {line_number}: {kind!r}"
            )
        pitched_event_count += 1

    if not event_count:
        raise ValueError("Jianpu JSONL contains no event rows")
    if not pitched_event_count:
        raise ValueError("Jianpu JSONL contains no pitched note or chord events")


def _ensure_test_musicxml(tmp: Path) -> Path:
    """Build a small, valid score without relying on artifacts from another test."""
    score = build_grand_staff(
        [[NoteSpec(["C4"], 1.0), NoteSpec(["D4"], 1.0),
          NoteSpec(["E4"], 1.0), NoteSpec(["F4"], 1.0)]],
        [[NoteSpec(["C3", "E3", "G3"], 4.0)]],
        key_name="C",
        title="Temporary OCR E2E Score",
    )
    source = tmp / "source.musicxml"
    score.write("musicxml", fp=str(source))
    if not source.is_file():
        raise RuntimeError(f"Failed to create test MusicXML source: {source}")
    return source


def _ensure_test_image(tmp: Path, source: Path) -> Path:
    """Render the temporary MusicXML source into a PNG for OMR."""
    mscore = find_musescore()
    if not mscore:
        raise RuntimeError("MuseScore 4 is required to generate the test image")

    target = tmp / "test_input.png"
    cmd = [mscore, "-r", "200", "-o", str(target), str(source)]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    actual = target.with_name(target.stem + "-1.png")
    if actual.exists() and not target.exists():
        actual.rename(target)
    if not target.exists():
        raise RuntimeError(f"Failed to generate test image: {target}")
    return target


def _missing_external_tools(*, pdf_input: bool = False) -> list[str]:
    missing = []
    if not is_audiveris_available():
        missing.append("Audiveris")
    if not find_musescore():
        missing.append("MuseScore")
    if pdf_input and (
        not shutil.which("pdfinfo") or not shutil.which("pdftoppm")
    ):
        missing.append("Poppler (pdfinfo and pdftoppm)")
    return missing


def test_ocr_e2e(tmp: Path, source: Path) -> None:
    """Full OCR pipeline: image -> Audiveris -> MusicXML -> MIDI -> jianpu -> PNG."""
    missing = _missing_external_tools()
    if missing:
        print(f"  [skip] Missing external tools for image OCR E2E: {', '.join(missing)}")
        return
    print("  Audiveris:", find_audiveris())
    print("  MuseScore:", find_musescore())

    img = _ensure_test_image(tmp, source)
    print(f"  Test image: {img} ({img.stat().st_size} bytes)")

    from src.main import run_pipeline

    results = run_pipeline(
        input_path=img,
        out_dir=tmp / "out",
        bpm=100,
        render_png=True,
        skip_ocr=False,
    )
    assert len(results) == 1
    r = results[0]
    assert r.musicxml and r.musicxml.exists()
    assert r.midi and r.midi.exists() and r.midi.stat().st_size > 0
    assert r.jianpu_txt and r.jianpu_txt.exists()
    assert r.rendered_png and r.rendered_png.exists() and r.rendered_png.stat().st_size > 1024
    assert r.requires_review
    assert r.review_report and r.review_report.is_file()
    review = json.loads(r.review_report.read_text(encoding="utf-8"))
    assert review["state"] == "needs_source_image_review"
    if r.publication_state == "complete":
        assert review["publication_state"] == "complete"

    jianpu = r.jianpu_txt.read_text(encoding="utf-8")
    _validate_jianpu_jsonl(jianpu)
    print(f"  MusicXML: {r.musicxml.name} ({r.musicxml.stat().st_size} bytes)")
    print(f"  MIDI    : {r.midi.name} ({r.midi.stat().st_size} bytes)")
    print(f"  jianpu  : {jianpu[:80]!r}")
    print(f"  PNG     : {r.rendered_png.name} ({r.rendered_png.stat().st_size} bytes)")


def _ensure_test_pdf(tmp: Path, source: Path) -> Path:
    """Render the temporary MusicXML source into a PDF for OMR."""
    mscore = find_musescore()
    if not mscore:
        raise RuntimeError("MuseScore 4 is required to generate the test PDF")
    target = tmp / "test_input.pdf"
    cmd = [mscore, "-o", str(target), str(source)]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    if not target.exists():
        raise RuntimeError(f"Failed to generate test PDF: {target}")
    return target


def test_ocr_pdf_e2e(tmp: Path, source: Path) -> None:
    """Full OCR pipeline with PDF input: PDF -> image -> Audiveris -> MusicXML -> MIDI -> jianpu -> PNG."""
    missing = _missing_external_tools(pdf_input=True)
    if missing:
        print(f"  [skip] Missing external tools for PDF OCR E2E: {', '.join(missing)}")
        return
    pdf = _ensure_test_pdf(tmp, source)
    print(f"  Test PDF: {pdf} ({pdf.stat().st_size} bytes)")

    from src.main import run_pipeline

    results = run_pipeline(
        input_path=pdf,
        out_dir=tmp / "out_pdf",
        bpm=100,
        render_png=True,
        skip_ocr=False,
    )
    assert len(results) == 1
    r = results[0]
    assert r.musicxml and r.musicxml.exists()
    assert r.midi and r.midi.exists()
    assert r.jianpu_txt and r.jianpu_txt.exists()
    assert r.rendered_png is not None
    assert r.rendered_png.is_file() and r.rendered_png.stat().st_size > 1024
    assert r.requires_review
    assert r.review_report and r.review_report.is_file()
    review = json.loads(r.review_report.read_text(encoding="utf-8"))
    assert review["state"] == "needs_source_image_review"
    jianpu = r.jianpu_txt.read_text(encoding="utf-8")
    _validate_jianpu_jsonl(jianpu)
    print(f"  PDF -> MusicXML: {r.musicxml.name}")
    print(f"  PDF -> MIDI    : {r.midi.name}")
    print(f"  PDF -> jianpu  : {jianpu[:80]!r}")
    print(f"  PDF -> PNG     : {r.rendered_png.name} ({r.rendered_png.stat().st_size} bytes)")


def test_ocr_handles_unavailable(tmp: Path) -> None:
    """When Audiveris is missing, raise a clear RuntimeError instead of crashing."""
    with patch("src.ocr.find_audiveris", return_value=None):
        try:
            image_to_musicxml(tmp / "nope.png", tmp, AudiverisConfig())
            raised = False
        except RuntimeError as error:
            raised = True
            assert "Audiveris" in str(error)
        assert raised, "Missing Audiveris should raise RuntimeError"


def main() -> int:
    print("=== OCR end-to-end test ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        source = _ensure_test_musicxml(tmp)
        print("\n[1] Full OCR pipeline (PNG input):")
        test_ocr_e2e(tmp, source)
        print("\n[2] Full OCR pipeline (PDF input):")
        test_ocr_pdf_e2e(tmp, source)
        print("\n[3] Audiveris unavailable -> clear error:")
        test_ocr_handles_unavailable(tmp)
    print("\nALL OCR E2E PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
