# Jianpu PDF Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the validated score model as an accurate, printable Jianpu PDF with aligned SATBB parts, lyrics, and rhythm symbols.

**Architecture:** Add a dedicated ReportLab renderer that consumes `ScoreModel` events and never reparses source notation. Keep layout coordinates independent of drawing so simultaneous events share the same x-position and can be unit-tested.

**Tech Stack:** Python, ReportLab, `pypdf` test utility, existing `music21` score model, `pdf2image` for optional raster inspection.

---

## Prerequisite

Run [the Score Model and Conversion Core plan](2026-10-22-score-model-core.md) first. The renderer consumes `ScoreModel`, `ScoreEvent`, `MeasureContext`, and the validated jianpu pitch mapping created by that plan.

```bash
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Task 1: Add the Renderer API and PDF Smoke Test

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-test.txt`
- Create: `src/render/jianpu_pdf.py`
- Create: `tests/test_jianpu_pdf.py`

- [ ] **Step 1: Add a failing PDF contract test**

```python
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfReader

from src.music_convert.musicxml_io import load_musicxml
from src.render.jianpu_pdf import render_jianpu_pdf


class JianpuPdfTests(unittest.TestCase):
    def test_writes_readable_one_page_pdf(self):
        score = load_musicxml(Path("tests/fixtures/g-major-two-bars.musicxml"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jianpu.pdf"
            render_jianpu_pdf(
                score, output, notation="movable", tonic=None,
                title="Renderer Test",
            )
            self.assertTrue(output.exists())
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
            reader = PdfReader(str(output))
            self.assertEqual(1, len(reader.pages))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("Renderer Test", text)
            self.assertIn("Soprano", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm the renderer failure**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: FAIL because `src.render.jianpu_pdf` does not exist.

- [ ] **Step 3: Add exact dependencies**

Add `reportlab>=4.2` to `requirements.txt`. Create `requirements-test.txt`:

```text
-r requirements.txt
pypdf>=5.0
```

- [ ] **Step 4: Implement the smallest renderer**

Create `render_jianpu_pdf(score: ScoreModel, output_path: str | Path, *, notation: str = "movable", tonic: str | None = None, title: str | None = None, font_path: str | Path | None = None) -> Path`. `notation` means movable/fixed do, not major/minor; resolve each event's major/minor key context from the model and use the core `map_pitch` API. Use `reportlab.pdfgen.canvas.Canvas` and `landscape(A4)`, create the output directory, write title and part labels, draw one measure system, and return the output path. Do not silently switch to a different renderer or report success before the file exists.

- [ ] **Step 5: Install the test dependency and run the test**

Run: `python -m pip install -r requirements-test.txt`
Expected: both dependency files install successfully.

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: `OK`; the PDF signature, page count, title, and part label are readable.

- [ ] **Step 6: Commit the renderer API**

```bash
git add requirements.txt requirements-test.txt src/render/jianpu_pdf.py tests/test_jianpu_pdf.py
git commit -m "feat: add jianpu pdf renderer"
```

## Task 2: Align Events by Measure Beat

**Files:**
- Modify: `src/render/jianpu_pdf.py`
- Modify: `tests/test_jianpu_pdf.py`

- [ ] **Step 1: Add a failing coordinate test**

For a four-beat measure, create events in two different parts at beat `1/2`; compute each x-coordinate from those event onsets and require equality. Also require beat `2` to appear to the right of beat `1/2`.

```python
from fractions import Fraction

from src.render.jianpu_pdf import event_x


class JianpuLayoutTests(unittest.TestCase):
    def test_equal_beats_share_x_coordinate(self):
        soprano_onset = Fraction(1, 2)
        alto_onset = Fraction(1, 2)
        self.assertEqual(
            event_x(soprano_onset, Fraction(4), 80.0, 400.0),
            event_x(alto_onset, Fraction(4), 80.0, 400.0),
        )
        self.assertLess(
            event_x(Fraction(1, 2), Fraction(4), 80.0, 400.0),
            event_x(Fraction(2), Fraction(4), 80.0, 400.0),
        )
```

- [ ] **Step 2: Run the layout test and confirm the missing helper**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: FAIL because `event_x` is not defined.

- [ ] **Step 3: Implement beat-proportional positioning**

Implement `event_x(onset: Fraction, measure_duration: Fraction, measure_x: float, measure_width: float) -> float` as `measure_x + float(onset / measure_duration) * measure_width`. Render every part using the same measure x/width. Group each part's events by `(measure_index, voice_id)`; draw barlines and measure numbers once per system, not once per voice.

- [ ] **Step 4: Add a five-part alignment regression**

Render the SATBB fixture and compare the calculated x-coordinate for each event at a shared onset across all five parts. Assert that all five coordinates are equal; assert the output part labels are exactly the five source labels.

- [ ] **Step 5: Run the tests and commit**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: `OK`.

```bash
git add src/render/jianpu_pdf.py tests/test_jianpu_pdf.py
git commit -m "feat: align jianpu parts by beat"
```

## Task 3: Draw Rhythm, Ties, Lyrics, and Octave Marks

**Files:**
- Modify: `src/render/jianpu_pdf.py`
- Modify: `tests/test_jianpu_pdf.py`

- [ ] **Step 1: Add symbol-presence and font-failure tests**

Test a quarter note, dotted note, eighth note, sixteenth note, rest, chord, octave-up note, octave-down note, tied note, and Chinese lyric. Assert the selected notation/tonic produces the same pitch tokens as `map_pitch`; test both major and minor model key contexts. Assert missing configured CJK font raises a clear `RuntimeError` when the model contains CJK text; an English-only fixture remains renderable with built-in Latin fonts.

- [ ] **Step 2: Run the tests and confirm missing-symbol failures**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: FAIL for rhythm-symbol assertions and the required CJK-font error.

- [ ] **Step 3: Implement vector notation and explicit font selection**

Draw pitch tokens using the core mapper with `notation` and `tonic`, resolving key mode from the event's active score context. Draw Latin text with a built-in Latin font; draw augmentation dots, octave dots, underlines, duration dashes, barlines, and per-pitch tie/slur curves using ReportLab vector primitives. Register a CJK TrueType font only from `font_path` or `JIANPU_CJK_FONT`. If the score contains CJK and no usable font is configured, raise `RuntimeError` naming the setting; do not fall back to a font known to omit glyphs.

- [ ] **Step 4: Verify text extraction and raster output**

Use `pypdf.PdfReader` to verify part labels and Latin headers. Convert the PDF with the existing `pdf2image` adapter at 150 DPI and assert a non-empty PNG is created; manually inspect the SATBB regression render for clipping, overlapping lyrics, and missing glyphs.

- [ ] **Step 5: Run the tests and commit**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: `OK`; manual inspection shows all symbols and lyric rows.

```bash
git add src/render/jianpu_pdf.py tests/test_jianpu_pdf.py
git commit -m "feat: draw jianpu rhythm and lyrics"
```

## Task 4: Paginate and Preserve Source Part Count

**Files:**
- Modify: `src/render/jianpu_pdf.py`
- Modify: `tests/test_jianpu_pdf.py`

- [ ] **Step 1: Add a failing multi-page test**

Render a fixture long enough to require two systems. Assert the PDF has at least two pages, every source part label appears, and no renderer-only solo part is introduced.

- [ ] **Step 2: Run and confirm the pagination failure**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: FAIL because the renderer currently draws only one system.

- [ ] **Step 3: Implement deterministic pagination**

Pack complete measures into each system using available landscape page width. Start a new page before a system exceeds the width or vertical page capacity. Repeat title/part labels where needed, retain measure numbering, and render only `ScoreModel.parts`.

- [ ] **Step 4: Run the complete renderer tests**

Run: `python -m unittest discover -s tests -p test_jianpu_pdf.py -v`
Expected: `OK`; the five-part fixture remains five parts on every page.

- [ ] **Step 5: Commit pagination**

```bash
git add src/render/jianpu_pdf.py tests/test_jianpu_pdf.py
git commit -m "feat: paginate jianpu pdf scores"
```

## Completion Check

- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Render the SATBB regression fixture and inspect the PDF after rasterization.
- [ ] Confirm the renderer reads only validated `ScoreModel` events and outputs exactly the source parts.
- [ ] Confirm the renderer fails clearly when a required CJK font is unavailable.
