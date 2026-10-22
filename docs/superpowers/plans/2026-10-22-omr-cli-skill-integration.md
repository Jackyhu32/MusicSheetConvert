# OMR, CLI, and Skill Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the command-line and AI Skill workflows truthful and stable for single- and multi-page inputs, with explicit review status and no invented score content.

**Architecture:** Keep Audiveris as an optional OMR adapter and rasterize PDFs into ordered pages. Convert page MusicXML into models, merge only when part identities and score context are unambiguous, and mark all OMR-derived results for source-image review. Expose the validated core and PDF renderer through one CLI contract; update the Skill to use that contract and to stop when its vision or tool capabilities are insufficient.

**Tech Stack:** Python CLI, Audiveris, `pdf2image`/Poppler, `music21`, ReportLab, YAML frontmatter.

---

## Prerequisites and Order

Run the [Score Model and Conversion Core plan](2026-10-22-score-model-core.md) and the [Jianpu PDF Renderer plan](2026-10-22-jianpu-pdf-renderer.md) first. This plan integrates their APIs and tests the full output bundle.

```bash
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

## Task 1: Merge Ordered Page Models Safely

**Files:**
- Modify: `src/music_convert/model.py`
- Modify: `src/music_convert/musicxml_io.py`
- Modify: `src/ocr/__init__.py`
- Create: `tests/test_page_merge.py`
- Create: `tests/fixtures/page-one.musicxml`
- Create: `tests/fixtures/page-two.musicxml`
- Create: `tests/fixtures/page-two-renamed-part.musicxml`

- [ ] **Step 1: Add failing page-merge tests**

Create two one-page MusicXML fixtures with the same five uniquely named parts and consecutive measure content. Add a test that verifies page order, five-part identity, measure reindexing, and source-page locations. Add a second test where page two renames or omits one part; require a `ValueError` and no merged output.

```python
import unittest
from pathlib import Path

from src.music_convert.musicxml_io import load_musicxml, merge_page_models


FIXTURES = Path(__file__).parent / "fixtures"


class PageMergeTests(unittest.TestCase):
    def test_same_parts_merge_in_page_order(self):
        pages = [
            load_musicxml(FIXTURES / "page-one.musicxml"),
            load_musicxml(FIXTURES / "page-two.musicxml"),
        ]
        merged = merge_page_models(pages)
        self.assertEqual(5, len(merged.parts))
        self.assertEqual(2, len(merged.measures))
        self.assertEqual(2, merged.parts[0].events[-1].source_location.page)

    def test_mismatched_parts_fail_closed(self):
        first = load_musicxml(FIXTURES / "page-one.musicxml")
        second = load_musicxml(FIXTURES / "page-two-renamed-part.musicxml")
        with self.assertRaisesRegex(ValueError, "part identities"):
            merge_page_models([first, second])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and confirm the missing-merge failure**

Run: `python -m unittest discover -s tests -p test_page_merge.py -v`  
Expected: FAIL because `merge_page_models` is not defined.

- [ ] **Step 3: Implement safe page merge and OMR isolation**

Add `SourceLocation(page, system, measure_number)` to each event. `merge_page_models` must require the same unique part names in the same normalized order, concatenate measures in input page order, carry forward key/time context only when a page explicitly inherits the prior score context, and mark unresolved page-boundary ties as review issues. Build the combined `music21` score and serialize it to the merged model's `source_musicxml`.

Change `run_pipeline` to give each page its own Audiveris output directory. Change `image_to_musicxml` to accept the exact expected output path or page-specific directory and remove its fallback that can return an unrelated stale `.mxl` from an earlier run.

- [ ] **Step 4: Run page-merge and OMR adapter tests**

Run: `python -m unittest discover -s tests -p test_page_merge.py -v`  
Expected: `OK`; valid parts merge in page order and mismatched parts fail without emitting a score.

- [ ] **Step 5: Commit page merging**

```bash
git add src/music_convert/model.py src/music_convert/musicxml_io.py src/ocr/__init__.py tests/test_page_merge.py tests/fixtures/page-one.musicxml tests/fixtures/page-two.musicxml
git commit -m "feat: merge ordered score pages safely"
```

## Task 2: Make the CLI Emit One Validated Output Bundle

**Files:**
- Modify: `src/main.py`
- Modify: `src/render/__init__.py`
- Modify: `tests/e2e_cli.py`
- Create: `tests/test_cli_outputs.py`

- [ ] **Step 1: Add failing CLI contract tests**

Use the existing MusicXML fixture and `unittest.mock.patch` for external OMR. Assert one `PipelineResult` exposes the source MusicXML, MIDI, jianpu text, jianpu PDF, and review report; assert the result keeps five parts and does not add a solo part. Assert a PDF with two mocked pages produces one merged score result, not two unrelated deliverables.

- [ ] **Step 2: Run and confirm the CLI contract failure**

Run: `python -m unittest discover -s tests -p test_cli_outputs.py -v`  
Expected: FAIL because `PipelineResult` has no `jianpu_pdf` or review status and the pipeline returns one result per page.

- [ ] **Step 3: Add the explicit conversion options**

Extend `build_parser()` with `--mode {movable,fixed}` (default `movable`), `--tonic`, and `--formats` (default `text,pdf,musicxml,midi`). Here `--mode` selects Jianpu notation; major/minor key mode comes from the model's active score context. Extend `PipelineResult` with `jianpu_pdf: Path | None`, `review_report: Path | None`, and `requires_review: bool`. Make `run_pipeline()` parse MusicXML once, validate the model, pass the notation mode and tonic to both the text formatter and `render_jianpu_pdf`, render selected formats from that model, and return one result for a whole input document.

- [ ] **Step 4: Add the review report and fail-closed behavior**

For OMR-derived input, set `requires_review=True` even if structural checks pass; structural checks cannot prove that OMR read the image correctly. Write `review.json` containing input path, page count, source part names, validation issue codes, source locations, and the explicit state `needs_source_image_review`. If part identities conflict, a required key/meter is missing, or validation has blocking issues, do not emit a final-complete status.

- [ ] **Step 5: Run CLI and legacy integration tests**

Run: `python -m unittest discover -s tests -p test_cli_outputs.py -v`  
Expected: `OK`; the PDF input creates a single merged score result and all requested artifacts.

Run: `python tests/e2e_cli.py`  
Expected: `E2E OK`.

- [ ] **Step 6: Commit the CLI contract**

```bash
git add src/main.py src/render/__init__.py tests/e2e_cli.py tests/test_cli_outputs.py
git commit -m "feat: emit validated score output bundle"
```

## Task 3: Replace the Skill's Invalid Metadata and Overclaims

**Files:**
- Modify: `skill.md`
- Create: `tests/skill_scenarios.md`
- Create: `tests/test_skill_metadata.py`

- [ ] **Step 1: Write capability and accuracy scenarios**

Add the following scenarios to `tests/skill_scenarios.md` before editing the Skill:

```markdown
## Scenario: SATBB source has no solo part
Input: Six-page SATBB source score; request only a Jianpu conversion.
Pass: Output has exactly the five source parts and no standalone melody page.

## Scenario: Minor movable-do
Input: A-minor score; default movable-do.
Pass: A is degree 6 and the Skill states the selected reference.

## Scenario: Fixed-do
Input: D-major score; user requests fixed-do.
Pass: C is degree 1 and D is degree 2; key signature does not move the numbers.

## Scenario: Ambiguous accidental
Input: A source note could be F-natural or F-sharp in a dense scan.
Pass: The Skill cites page, part, and measure, asks for confirmation, and does not claim a final accurate PDF.

## Scenario: Missing visual capability
Input: Image/PDF supplied to a text-only agent with no OMR.
Pass: The Skill requests MusicXML or readable page images and does not fabricate extracted notes.
```

- [ ] **Step 2: Add a failing frontmatter check**

```python
from pathlib import Path
import unittest
import yaml


class SkillMetadataTests(unittest.TestCase):
    def test_skill_has_yaml_frontmatter(self):
        text = Path("skill.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        _, frontmatter, _ = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        self.assertEqual("staff-to-jianpu", metadata["name"])
        self.assertTrue(metadata["description"].strip())


if __name__ == "__main__":
    unittest.main()
```

Add `PyYAML>=6.0` to `requirements-test.txt` and run `python -m unittest discover -s tests -p test_skill_metadata.py -v`. Expected before editing: FAIL because `skill.md` begins with `## name:` instead of `---`.

- [ ] **Step 3: Rewrite the Skill workflow**

Replace the embedded unverified renderer script with concise, executable guidance. Start `skill.md` with:

```yaml
---
name: staff-to-jianpu
description: Convert staff scores from images, PDFs, or MusicXML into verified Jianpu text and PDF, preserving parts, pitch, rhythm, ties, and lyrics.
---
```

Document the actual CLI flags from Task 2; default to movable-do; define minor tonic as `6`; define fixed-do as `C=1`; require event-level validation, visual review of OMR, explicit unresolved locations, source part-count preservation, and the rule that no unrequested part or standalone melody may be added. If the agent lacks image access and Audiveris is unavailable, stop and request MusicXML or readable score images.

- [ ] **Step 4: Run the Skill metadata and scenario checks**

Run: `python -m unittest discover -s tests -p test_skill_metadata.py -v`  
Expected: `OK`.

Run each scenario in `tests/skill_scenarios.md` against a fresh agent session with the revised Skill loaded. Record pass/fail and the agent's response in the test log. The current sandbox cannot invoke Gemini Spark; do not claim Spark integration passed unless these scenarios are run there.

- [ ] **Step 5: Commit the Skill update**

```bash
git add skill.md requirements-test.txt tests/test_skill_metadata.py tests/skill_scenarios.md
git commit -m "docs: make staff-to-jianpu skill verifiable"
```

## Task 4: Repair Reproducible Setup and Document the Supported Pipeline

**Files:**
- Modify: `scripts/install.sh`
- Modify: `README.md`
- Modify: `tests/ocr_e2e.py`

- [ ] **Step 1: Add a setup-script syntax check**

Run `bash -n scripts/install.sh` and verify setup defaults are documented. The current script's `set PY=...` and `set VENV=...` lines are not Bash variable assignments.

- [ ] **Step 2: Fix the Unix setup script**

Use this implementation:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$ROOT/requirements-test.txt"
printf 'Install complete. Activate with: source "%s/bin/activate"\n' "$VENV_DIR"
```

- [ ] **Step 3: Update the README**

Document the three plans' supported path, the `python -m src.main` flags, the external requirements (Audiveris for OMR, Poppler for PDF rasterization, a configured CJK font for Chinese lyrics), the review-report meaning, and exact unit/integration commands. Correct the README claim that tests auto-skip missing Python dependencies; only external-tool checks may skip.

- [ ] **Step 4: Remove stale E2E assumptions and verify commands**

Change `tests/ocr_e2e.py` to create the MusicXML fixture inside `TemporaryDirectory` instead of requiring `data/output_demo/bach_prelude_m1_m4.musicxml`. Run:

```bash
bash -n scripts/install.sh
python -m unittest discover -s tests -v
python tests/smoke.py
python tests/e2e_cli.py
python tests/complex_e2e.py
python tests/ocr_e2e.py
```

Expected: deterministic Python tests pass; OMR/render integration tests either pass with installed tools or print an explicit external-tool skip.

- [ ] **Step 5: Commit reproducibility fixes**

```bash
git add scripts/install.sh README.md tests/ocr_e2e.py
git commit -m "fix: make score conversion setup reproducible"
```

## Completion Check

- [ ] All Python unit tests pass in `.venv`.
- [ ] Existing MusicXML, MIDI, and complex-score smoke tests pass.
- [ ] Multi-page PDF input produces one ordered score bundle or fails closed on ambiguous parts.
- [ ] Every OMR result carries a source-image review status.
- [ ] Skill scenarios pass without adding a solo page or guessing uncertain notes.
- [ ] Do not claim Gemini Spark validation until tests have actually run in Spark.
- [ ] Do not claim full benchmark accuracy until the user supplies a source MusicXML or approves a manually verified excerpt.
