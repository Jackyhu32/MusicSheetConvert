"""Smoke test: MusicXML -> MIDI -> jianpu-text roundtrip (no external OMR required)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Make ``import src.xxx`` work when running ``python tests/smoke.py``.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.music_convert import core


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths><mode>major</mode></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>B</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""


def test_xml_to_midi_to_jianpu(tmp: Path) -> None:
    xml_path = tmp / "sample.musicxml"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")

    midi_path = core.musicxml_to_midi(xml_path, tmp / "sample.mid")
    assert midi_path.exists() and midi_path.stat().st_size > 0

    import json

    jianpu = core.musicxml_to_jianpu_text(xml_path)
    print("jianpu:", jianpu)
    events = [json.loads(line) for line in jianpu.splitlines()
              if json.loads(line)["type"] == "event"]
    assert [event["pitches"] for event in events] == ["1", "2", "3", "4", "5", "6", "7", "1^1"]


def test_jianpu_to_midi_roundtrip(tmp: Path) -> None:
    jianpu = "1 2 3 4 | 5 6 7 1+"
    midi = core.jianpu_text_to_midi(jianpu, tmp / "roundtrip.mid",
                                    options=core.ConvertOptions(bpm=100))
    assert midi.exists() and midi.stat().st_size > 0

    xml = core.jianpu_text_to_musicxml(jianpu, tmp / "roundtrip.musicxml",
                                        options=core.ConvertOptions(bpm=100))
    assert xml.exists() and xml.stat().st_size > 0


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_xml_to_midi_to_jianpu(tmp)
        test_jianpu_to_midi_roundtrip(tmp)
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
