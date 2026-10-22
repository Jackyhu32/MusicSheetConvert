# MusicSheetConvert

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![DOI](https://img.shields.io/badge/DOI-zenodo.20604622-blue.svg)](https://doi.org/10.5281/zenodo.20604622)

> A Python toolkit for converting between **staff notation**, **numbered notation
> (jianpu)**, **MIDI**, and **MusicXML**, with optional optical music
> recognition (Audiveris) and staff-notation rendering (MuseScore).

---

## Table of Contents

- [Features](#features)
- [Demo](#demo)
- [Architecture](#architecture)
- [Supported Implementation Path](#supported-implementation-path)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Jianpu JSONL](#jianpu-jsonl)
- [Testing](#testing)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Score-model pipeline** — parse and validate MusicXML, then publish selected
  Jianpu JSONL, paginated Jianpu PDF, editable MusicXML, and MIDI artifacts.
- **Image/PDF OMR** — preprocess sheet images and use Audiveris to produce
  MusicXML; rasterize PDF pages with Poppler and merge pages in source order.
- **Source review reporting** — OMR-derived results are marked for review
  against the original image, even when conversion and publication succeed.
- **Complex-score builders** for grand staff, multiple key signatures
  (C / G / D / F / Bb / Eb / Am / Em / Dm), ii-V-I 7th-chord progressions, and
  the first four measures of Bach's Prelude in C major (BWV 846).
- **Optional staff PNG rendering** via MuseScore when `--render` is requested.
- **Pure-Python core** — no daemon, no web server, just a CLI and a library.

---

## Demo

```bash
python -m src.main --demo bach_prelude --render --out data/demo_bach
```

The CLI prints the paths it actually published. Each invocation writes to a
unique run directory under the `--out` root.

---

## Architecture

```
PDF / image --(PDF: Poppler)--> pages --(OpenCV)--> Audiveris OMR
MusicXML ----------------------------------------------+
                                                       v
                                    ScoreModel -> validation
                                      |       |       |       |
                                   JSONL   Jianpu PDF MusicXML MIDI
                                      |
                              optional staff PNG (--render)
```

| Module | Responsibility |
|--------|----------------|
| `src/main.py` | CLI, validation, and transactional output-bundle orchestration. |
| `src/music_convert/model.py` | Measure-, part-, voice-, and event-aware score model. |
| `src/music_convert/core.py` | Validated score-model conversion to MIDI and Jianpu JSONL. |
| `src/music_convert/advanced.py` | Grand-staff, key-signature, chord, Bach-prelude builders. |
| `src/ocr/__init__.py` | Audiveris 5.x adapter with auto-discovery. |
| `src/preprocess/__init__.py` | Image / PDF preprocessing (grayscale, adaptive threshold, scaling). |
| `src/render/jianpu_pdf.py` | Paginated Jianpu PDF rendering, including exact supported rhythms and lyrics. |
| `src/render/__init__.py` | Optional MuseScore staff PNG rendering and Jianpu JSONL file output. |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for more detail.

## Supported Implementation Path

The implemented workflow follows three coordinated plans:

1. [Score Model and Conversion Core](docs/superpowers/plans/2026-10-22-score-model-core.md) parses MusicXML into validated, measure- and event-aware score data, preserving parts, exact timing, lyrics, ties, and the editable staff-score source.
2. [Jianpu PDF Renderer](docs/superpowers/plans/2026-10-22-jianpu-pdf-renderer.md) renders that validated model as paginated Jianpu PDF with aligned parts, supported rhythms, ties, and lyrics.
3. [OMR, CLI, and Skill Integration](docs/superpowers/plans/2026-10-22-omr-cli-skill-integration.md) routes image/PDF inputs through OMR, merges compatible PDF pages in order, publishes the selected artifact bundle, and marks every OMR result for source-image review.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Unk1ndledAC/MusicSheetConvert.git
cd MusicSheetConvert
```

### 2. Create a Python venv and install dependencies

**Linux / macOS (POSIX shell)**

```bash
./scripts/install.sh
```

The script defaults to `python3` and `<repo>/.venv`, installs
`requirements-test.txt`, and prints the activation command. Override its
settings with `PYTHON_BIN=/path/to/python` or `VENV_DIR=/path/to/venv`. Activate
with `source .venv/bin/activate`.

**Windows (PowerShell)**

```powershell
py -m venv .venv
& .\.venv\Scripts\python -m pip install --upgrade pip
& .\.venv\Scripts\python -m pip install -r requirements-test.txt
```

Activate in PowerShell with `./.venv/Scripts/Activate.ps1`, or in Command
Prompt with `.venv\Scripts\activate.bat`. The POSIX `scripts/install.sh` is
not a Windows/Git Bash setup script. The legacy `scripts\install.bat` requires
configuring its `PY` and `VENV` placeholders before use and installs
`requirements.txt`; it is not ready to run without configuration.

### 3. Install external tools

| Tool / setting | Used for | Setup |
|---------------|----------|-------|
| **Audiveris 5.x** | OMR for CLI image and PDF inputs | <https://github.com/Audiveris/audiveris/releases> |
| **Poppler** (`pdfinfo`, `pdftoppm`) | Rasterizing PDF pages through `pdf2image` | Install Poppler and make its tools available on `PATH`. |
| **MuseScore** | Optional staff PNG from `--render`; also used by rendering integration tests | <https://musescore.org/download> |
| **CJK font** | Chinese/Japanese/Korean lyrics in Jianpu PDF | Configure `JIANPU_CJK_FONT` to a font file containing all lyric glyphs. |

Set `AUDIVERIS_EXE` and `MUSESCORE_EXE` when the executables are not on `PATH`;
the CLI also accepts `--audiveris-bin` for Audiveris. `JIANPU_CJK_FONT` is only
needed when the source contains CJK lyrics and a Jianpu PDF is requested.

---

## Quick Start

### Convert an image

```bash
python -m src.main path/to/score.png --out data/output --bpm 100
```

Image and PDF inputs run through image preprocessing and Audiveris OMR. By
default the CLI requests all four output formats: Jianpu JSONL (`text`),
Jianpu PDF (`pdf`), MusicXML, and MIDI. Output is published under a unique
directory such as `data/output/score-<run-id>/`:

```
score-<run-id>/
├── jianpu/
│   ├── merged.txt  # JSON Lines, not plain token notation
│   └── merged.pdf  # paginated Jianpu PDF
├── midi/merged.mid
├── musicxml/merged.musicxml
└── review.json     # OMR source-image review status
```

The OMR MusicXML is an editable staff-notation score, not a rendering of the
Jianpu PDF. `--render` additionally asks MuseScore to write a staff-notation
PNG. Temporary preprocessed images and per-page OMR files are removed after
the merged result is built.

### Convert a multi-page PDF

```bash
python -m src.main path/to/scorebook.pdf --out data/output
```

PDF pages are rasterized in order and merged into one score only when the part
identities and score context are unambiguous. The editable merged MusicXML is
published as `musicxml/merged.musicxml`.

### Convert an existing MusicXML score

```bash
python -m src.main path/to/score.musicxml --out data/output
```

The source MusicXML is retained as editable staff notation in the bundle.

### Generate a complex score from a preset (no input file)

```bash
# Two-hand grand staff in any of the supported keys
python -m src.main --demo grand_staff --key Bb --render --out data/demo_bb

# ii-V-I 7th-chord progression
python -m src.main --demo chord_progression --key C --render --out data/demo_c

# All 9 supported key signatures in one piece
python -m src.main --demo key_demonstration --render --out data/demo_keys

# First 4 measures of Bach's Prelude in C major
python -m src.main --demo bach_prelude --render --out data/demo_bach
```

### Review OMR output

Every published OMR result sets `requires_review=true` and includes `review.json`
with state `needs_source_image_review`. Review the source image against the
transcription before relying on the notes. `publication_state=complete` only
means the output bundle was published; it does not mean the score was verified
against its source. If blocking structural issues prevent conversion, the
pipeline can publish a `review_only` report without final conversion files.

### Use as a Python library

```python
from pathlib import Path
from src.music_convert import core
from src.music_convert.advanced import build_grand_staff, NoteSpec
from src.ocr import image_to_musicxml
from src.render import musicxml_to_png

# 1) MusicXML -> MIDI
core.musicxml_to_midi("in.musicxml", "out.mid", core.ConvertOptions(bpm=100))

# 2) MusicXML -> Jianpu JSONL
print(core.musicxml_to_jianpu_text("in.musicxml"))

# 3) Build a complex score from scratch
score = build_grand_staff(
    right_hand_measures=[[NoteSpec(["C4"], 1.0), NoteSpec(["D4"], 1.0),
                         NoteSpec(["E4"], 1.0), NoteSpec(["F4"], 1.0)]],
    left_hand_measures=[[NoteSpec(["C3", "E3", "G3"], 4.0)]],
    key_name="C", title="Demo"
)

# 4) OMR (image -> MusicXML)
xml_path = image_to_musicxml("score.png", Path("data/output/musicxml"))

# 5) Render MusicXML to PNG via MuseScore
musicxml_to_png(xml_path, Path("data/output/rendered/score.png"))
```

---

## CLI Reference

```
python -m src.main [INPUT] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `INPUT` | PDF, PNG, JPG/JPEG, BMP, TIFF, MusicXML, or MXL input. Omit when using `--demo`. |
| `--out DIR` | Output root directory (default `./data/output`). |
| `--bpm N` | Fallback MIDI tempo when the score has no tempo (default `90`). |
| `--render` | Additionally render a staff-notation PNG via MuseScore. |
| `--skip-ocr` | Guard flag intended for MusicXML input; image/PDF input with this flag fails. MusicXML inputs bypass OMR based on their extension even without it. |
| `--audiveris-bin PATH` | Audiveris executable path for image/PDF OMR. |
| `--mode {movable,fixed}` | Jianpu notation mode (default `movable`; source major/minor mode remains in effect). |
| `--tonic NAME` | Optional explicit Jianpu tonic, e.g. `C`, `F#`, or `Bb`. |
| `--formats LIST` | Comma-separated selection from `text,pdf,musicxml,midi`; default `text,pdf,musicxml,midi`. No duplicates. |
| `--demo NAME` | Generate one of `grand_staff`, `chord_progression`, `key_demonstration`, or `bach_prelude`. |
| `--key NAME` | Preset key for generated scores; default `C`; choices `C,G,D,F,Bb,Eb,Am,Em,Dm`. |
| `--title TEXT` | Title for a generated score. |

---

## Jianpu JSONL

The `text` artifact is UTF-8 JSON Lines, not the legacy whitespace-separated
Jianpu token string. Each part begins with a `{"type":"part",...}` row followed
by one `{"type":"event",...}` row per source event. Event rows retain part,
measure, staff, voice, exact measure-local onset and duration, event kind,
Jianpu pitches, written pitches, per-pitch ties, lyrics, and grace-event
status. Chords remain one event with multiple pitches; rests use pitch `0`.
Fractions are exact integer or `numerator/denominator` strings.

---

## Testing

Install the Python test dependencies first. Missing Python packages required by
the tests do not auto-skip; install `requirements-test.txt` before running them.
Only checks for optional external executables may skip, and those checks print
the missing tool.

```bash
# Install dependencies and run unit tests
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v

# Syntax-check the Unix setup script
bash -n scripts/install.sh

# Integration / end-to-end checks
python tests/smoke.py
python tests/e2e_cli.py
python tests/complex_e2e.py
python tests/ocr_e2e.py
```

`tests/complex_e2e.py` parses Jianpu JSONL with the standard-library `json`
module. It skips only MuseScore-dependent PNG rendering and MIDI round-trip
checks when MuseScore is unavailable. The OCR script skips its image OMR check
when Audiveris or MuseScore is unavailable, and skips its PDF OMR check when
Audiveris, MuseScore, or Poppler is unavailable.

---

## Known Limitations

- **OMR is not proofread** — recognition can misread notes, rhythms, lyrics, or
  part identities, especially on noisy or dense scores. Always compare a
  published OMR result with the source image.
- **CJK lyric PDFs need a configured font** — set `JIANPU_CJK_FONT` to a font
  that contains every lyric glyph; PDF generation fails clearly if it is absent.
- **Unsupported or ambiguous score data fails closed** — blocking validation
  issues prevent final outputs, and unsupported Jianpu PDF layouts/events may
  be rejected rather than silently approximated.
- `publication_state=complete` records successful publication only; it is not
  an accuracy or source-review verdict.

---

## Contributing

We welcome issues and pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and the contribution workflow.

---

## License

This project is released under the **MIT License**. See [LICENSE](LICENSE)
for the full text.
