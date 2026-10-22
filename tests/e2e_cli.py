"""End-to-end test: invoke the main pipeline via the CLI (MusicXML input, OCR skipped)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.music_convert import core  # noqa: F401  (kept for future direct use)

SAMPLE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        xml = td_p / "twinkle.musicxml"
        xml.write_text(SAMPLE, encoding="utf-8")
        out = td_p / "out"

        from src.main import run_pipeline

        results = run_pipeline(
            input_path=xml,
            out_dir=out,
            bpm=120,
            render_png=False,
            skip_ocr=True,
            mode="fixed",
        )
        for r in results:
            print("===", r)
            assert r.musicxml and r.musicxml.exists()
            assert r.midi and r.midi.exists() and r.midi.stat().st_size > 0
            assert r.jianpu_txt and r.jianpu_txt.exists()
            assert r.jianpu_pdf and r.jianpu_pdf.exists()
            assert r.publication_state == "complete"
            print(r.jianpu_txt.read_text(encoding="utf-8"))
    print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
