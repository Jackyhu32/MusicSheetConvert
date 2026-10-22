"""Paginated Jianpu PDF rendering from a validated score model."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
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


def event_x(
    onset: Fraction,
    measure_duration: Fraction,
    measure_x: float,
    measure_width: float,
) -> float:
    """Return a beat-proportional x coordinate within a measure."""
    if measure_duration <= 0:
        raise ValueError("measure_duration must be positive")
    return measure_x + float(onset / measure_duration) * measure_width


def render_jianpu_pdf(
    score: ScoreModel,
    output_path: str | Path,
    *,
    notation: str = "movable",
    tonic: str | None = None,
    title: str | None = None,
    font_path: str | Path | None = None,
) -> Path:
    """Render complete measure systems across landscape A4 pages.

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
    measures = sorted(score.measures, key=lambda item: item.index)
    page_width, page_height = landscape(A4)
    document_title = score.title if title is None else title
    system_x = 150.0
    system_right = page_width - 36.0
    available_width = system_right - system_x
    minimum_measure_width = 80.0
    measures_per_system = max(1, int(available_width // minimum_measure_width))
    measure_groups = [
        measures[offset:offset + measures_per_system]
        for offset in range(0, len(measures), measures_per_system)
    ] or [[]]

    lane_spacing = 10.0
    row_padding = 20.0
    minimum_row_height = 54.0
    part_lane_keys = [
        sorted({(event.staff_number, event.voice_id) for event in part.events})
        for part in score.parts
    ]
    row_heights = [
        max(
            minimum_row_height,
            max(1, len(lane_keys)) * lane_spacing + row_padding,
        )
        for lane_keys in part_lane_keys
    ]
    available_height = page_height - 86.0 - 36.0
    ensemble_height = sum(row_heights)
    if ensemble_height > available_height:
        raise ValueError(
            "ensemble lane layout cannot fit on a landscape page; "
            "reduce the number of parts or lanes"
        )

    def require_text_fits(text: str, font_name: str, font_size: float, width: float):
        if stringWidth(text, font_name, font_size) > width:
            raise ValueError(
                f"text {text!r} cannot fit within its horizontal bounds"
            )

    require_text_fits(
        document_title,
        "Helvetica-Bold",
        18,
        system_right - 36.0,
    )
    for part in score.parts:
        require_text_fits(
            part.name,
            "Helvetica-Bold",
            11,
            system_x - 36.0 - 12.0,
        )

    for measure_group in measure_groups:
        measure_width = available_width / len(measure_group) if measure_group else 0.0
        measure_layout = {
            measure.index: (position, measure)
            for position, measure in enumerate(measure_group)
        }
        for position, measure in enumerate(measure_group):
            measure_x = system_x + position * measure_width
            require_text_fits(
                measure.number,
                "Helvetica",
                9,
                measure_x + measure_width - measure_x,
            )
        for part in score.parts:
            lane_events: dict[tuple[str, str], list[ScoreEvent]] = {}
            for event in part.events:
                if event.measure_index not in measure_layout:
                    continue
                lane_events.setdefault(
                    (event.staff_number, event.voice_id), []
                ).append(event)

            for events in lane_events.values():
                ordered_events = sorted(
                    events,
                    key=lambda event: (
                        measure_layout[event.measure_index][0],
                        event.onset,
                    ),
                )
                for event_index, event in enumerate(ordered_events):
                    position, measure = measure_layout[event.measure_index]
                    measure_x = system_x + position * measure_width
                    x = event_x(
                        event.onset,
                        measure.duration,
                        measure_x,
                        measure_width,
                    )
                    cell_right = measure_x + measure_width
                    if event_index + 1 < len(ordered_events):
                        next_event = ordered_events[event_index + 1]
                        next_position, next_measure = measure_layout[
                            next_event.measure_index
                        ]
                        next_x = event_x(
                            next_event.onset,
                            next_measure.duration,
                            system_x + next_position * measure_width,
                            measure_width,
                        )
                        cell_right = min(cell_right, next_x)

                    token = _event_token(
                        event,
                        notation=notation,
                        context=contexts.get(event.measure_index),
                    )
                    require_text_fits(
                        token,
                        "Helvetica",
                        11,
                        system_right - x,
                    )
                    if stringWidth(token, "Helvetica", 11) > cell_right - x:
                        raise ValueError(
                            f"event token {token!r} cannot fit within its rhythmic cell"
                        )

    pages = measure_groups
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = Canvas(str(output), pagesize=(page_width, page_height))
    pdf.setTitle(document_title)

    for page_index, page_measures in enumerate(pages):
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawCentredString(page_width / 2, page_height - 42, document_title)

        measure_width = available_width / len(page_measures) if page_measures else 0.0
        measure_layout = {
            measure.index: (position, measure)
            for position, measure in enumerate(page_measures)
        }
        page_parts = range(len(score.parts))
        row_y = {}
        current_y = page_height - 86
        for part_index in page_parts:
            row_y[part_index] = current_y
            current_y -= row_heights[part_index]

        if page_measures and score.parts:
            last_part_index = len(score.parts) - 1
            last_lane_count = max(1, len(part_lane_keys[last_part_index]))
            system_top = row_y[0] + 18
            system_bottom = (
                row_y[last_part_index] - (last_lane_count - 1) * lane_spacing - 18
            )
            pdf.setFont("Helvetica", 9)
            pdf.setLineWidth(0.7)
            for position, measure in enumerate(page_measures):
                measure_x = system_x + position * measure_width
                pdf.drawString(measure_x, system_top + 4, measure.number)
                barline_x = measure_x + measure_width
                pdf.line(barline_x, system_top, barline_x, system_bottom)

        for part_index in page_parts:
            part = score.parts[part_index]
            y = row_y[part_index]
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(36, y, part.name)
            pdf.setFont("Helvetica", 11)

            lane_keys = part_lane_keys[part_index]
            lanes = {key: lane for lane, key in enumerate(lane_keys)}
            grouped_events: dict[tuple[int, str, str], list[ScoreEvent]] = {}
            for event in part.events:
                if event.measure_index not in measure_layout:
                    continue
                group_key = (event.measure_index, event.staff_number, event.voice_id)
                grouped_events.setdefault(group_key, []).append(event)

            for (measure_index, staff_number, voice_id), events in sorted(
                grouped_events.items()
            ):
                position, measure = measure_layout[measure_index]
                measure_x = system_x + position * measure_width
                lane_y = y - lanes[(staff_number, voice_id)] * lane_spacing
                for event in sorted(
                    events,
                    key=lambda item: (item.onset, item.staff_number),
                ):
                    token = _event_token(
                        event,
                        notation=notation,
                        context=contexts.get(event.measure_index),
                    )
                    pdf.drawString(
                        event_x(
                            event.onset,
                            measure.duration,
                            measure_x,
                            measure_width,
                        ),
                        lane_y,
                        token,
                    )

        if page_index < len(pages) - 1:
            pdf.showPage()

    pdf.save()
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(
            f"PDF renderer did not produce the expected output: {output}"
        )
    return output
