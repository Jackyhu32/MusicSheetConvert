"""Basic one-page Jianpu PDF rendering from a validated score model."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas

from src.music_convert.jianpu import map_pitch
from src.music_convert.model import ScoreEvent, ScoreModel
from src.music_convert.validation import validate_score


_MAJOR_TONICS = {
    -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb",
    -1: "F", 0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B",
    6: "F#", 7: "C#",
}
_MINOR_TONICS = {
    -7: "Ab", -6: "Eb", -5: "Bb", -4: "F", -3: "C", -2: "G",
    -1: "D", 0: "A", 1: "E", 2: "B", 3: "F#", 4: "C#",
    5: "G#", 6: "D#", 7: "A#",
}


def _movable_contexts(
    score: ScoreModel, tonic: str | None
) -> dict[int, tuple[str, str]]:
    contexts: dict[int, tuple[str, str]] = {}
    active_mode: str | None = None
    active_fifths: int | None = None
    for measure in sorted(score.measures, key=lambda item: item.index):
        if measure.mode is not None:
            if measure.mode not in ("major", "minor"):
                raise ValueError(
                    f"missing_key_mode: unsupported mode {measure.mode!r}"
                )
            active_mode = measure.mode
        if measure.fifths is not None:
            active_fifths = measure.fifths
        if active_mode is None:
            raise ValueError(
                "missing_key_mode: movable notation requires a model key mode"
            )

        measure_tonic = tonic
        if measure_tonic is None:
            if active_fifths is None:
                raise ValueError(
                    "missing_tonic: movable notation requires a model key signature"
                )
            key_table = _MAJOR_TONICS if active_mode == "major" else _MINOR_TONICS
            measure_tonic = key_table.get(active_fifths)
            if measure_tonic is None:
                raise ValueError(
                    f"missing_tonic: unsupported key signature {active_fifths}"
                )
        contexts[measure.index] = (measure_tonic, active_mode)
    return contexts


def _event_token(
    event: ScoreEvent,
    *,
    notation: str,
    context: tuple[str, str] | None,
) -> str:
    if event.kind == "rest":
        return "0"

    event_tonic, key_mode = context if context is not None else (None, None)
    tokens = []
    for pitch in event.effective_sounding_pitches:
        degree, octave = map_pitch(
            pitch,
            tonic=event_tonic,
            key_mode=key_mode,
            notation=notation,
        )
        suffix = f"^{octave}" if octave > 0 else f"v{-octave}" if octave < 0 else ""
        tokens.append(f"{degree}{suffix}")
    return "+".join(tokens)


def render_jianpu_pdf(
    score: ScoreModel,
    output_path: str | Path,
    *,
    notation: str = "movable",
    tonic: str | None = None,
    title: str | None = None,
    font_path: str | Path | None = None,
) -> Path:
    """Render each part's event tokens on one landscape A4 PDF page.

    ``font_path`` is accepted for API compatibility; this basic renderer uses
    ReportLab's built-in Latin font. CJK font registration is handled by a
    later rendering task.
    """
    if notation not in ("movable", "fixed"):
        raise ValueError("notation must be 'movable' or 'fixed'")

    issues = validate_score(score)
    if issues:
        codes = ", ".join(dict.fromkeys(issue.code for issue in issues))
        raise ValueError(f"score validation failed: {codes}")

    contexts = _movable_contexts(score, tonic) if notation == "movable" else {}
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = landscape(A4)
    document_title = score.title if title is None else title
    pdf = Canvas(str(output), pagesize=(page_width, page_height))
    pdf.setTitle(document_title)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(page_width / 2, page_height - 42, document_title)

    y = page_height - 86
    for part in score.parts:
        ordered_events = sorted(
            part.events,
            key=lambda event: (
                event.measure_index,
                event.onset,
                event.staff_number,
                event.voice_id,
            ),
        )
        tokens = [
            _event_token(
                event,
                notation=notation,
                context=contexts.get(event.measure_index),
            )
            for event in ordered_events
        ]
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(36, y, part.name)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(120, y, " ".join(tokens))
        y -= 54

    pdf.save()
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(
            f"PDF renderer did not produce the expected output: {output}"
        )
    return output
