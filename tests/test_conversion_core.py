import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pretty_midi

from src.music_convert import core


ROOT = Path(__file__).resolve().parent.parent
G_MAJOR = ROOT / "tests" / "fixtures" / "g-major-two-bars.musicxml"
SATBB = ROOT / "tests" / "fixtures" / "satbb-two-measures.musicxml"

SIGNATURE_CHANGE_XML = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P"><part-name>Voice</part-name></score-part></part-list>
  <part id="P">
    <measure number="1"><attributes><divisions>1</divisions>
      <key><fifths>0</fifths><mode>major</mode></key><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
    <measure number="2"><attributes><key><fifths>1</fifths><mode>major</mode></key></attributes>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration></note>
    </measure>
  </part>
</score-partwise>
"""


EVENTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Event Semantics</work-title></work>
  <part-list><score-part id="P"><part-name>Voice</part-name></score-part></part-list>
  <part id="P">
    <measure number="1">
      <attributes>
        <divisions>3</divisions>
        <key><fifths>0</fifths><mode>major</mode></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>3</duration><tie type="start"/><voice>1</voice>
        <lyric number="2"><syllabic>single</syllabic><text>星\t光\n夜</text></lyric>
      </note>
      <note>
        <chord/><pitch><step>E</step><octave>4</octave></pitch>
        <duration>3</duration><voice>1</voice>
      </note>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>3</duration><tie type="stop"/><voice>1</voice>
      </note>
      <note><rest/><duration>6</duration><voice>1</voice></note>
    </measure>
    <measure number="2">
      <note><pitch><step>D</step><octave>4</octave></pitch>
        <duration>3</duration><voice>1</voice></note>
      <note><pitch><step>D</step><octave>4</octave></pitch>
        <duration>3</duration><voice>1</voice></note>
      <note><rest/><duration>6</duration><voice>1</voice></note>
    </measure>
  </part>
</score-partwise>
"""

NO_KEY_XML = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P"><part-name>Voice</part-name></score-part></part-list>
  <part id="P"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>
  </measure></part>
</score-partwise>
"""

INVALID_TIMELINE_XML = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P"><part-name>Voice</part-name></score-part></part-list>
  <part id="P"><measure number="1">
    <attributes><divisions>1</divisions><key><fifths>0</fifths><mode>major</mode></key>
      <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>5</duration></note>
  </measure></part>
</score-partwise>
"""


def rows(text):
    return [json.loads(line) for line in text.splitlines()]


class ConversionCoreTests(unittest.TestCase):
    def write_xml(self, directory, name, content):
        path = Path(directory) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_movable_g_major_uses_tonic_and_keeps_measure_local_timing(self):
        with patch(
            "src.music_convert.core.load_musicxml",
            wraps=core.load_musicxml,
        ) as load, patch(
            "src.music_convert.core.validate_score",
            wraps=core.validate_score,
        ) as validate:
            output = core.musicxml_to_jianpu_text(G_MAJOR, mode="movable")
        self.assertEqual(1, load.call_count)
        self.assertEqual(1, validate.call_count)

        converted = rows(output)
        headers = [row for row in converted if row["type"] == "part"]
        events = [row for row in converted if row["type"] == "event"]
        self.assertEqual(["S"], [row["part"] for row in headers])
        self.assertEqual(["1", "2", "3", "4"], [row["pitches"] for row in events[:4]])
        self.assertEqual(("1", "1", "0", "1"), (
            events[0]["pitches"],
            events[0]["measure"],
            events[0]["onset"],
            events[0]["duration"],
        ))
        second_measure = [row for row in events if row["measure"] == "2"]
        self.assertEqual(
            [("0", "1/3"), ("1/3", "1/3"), ("2/3", "1/3")],
            [(row["onset"], row["duration"]) for row in second_measure[:3]],
        )
        self.assertEqual("rest", second_measure[3]["kind"])

    def test_key_signature_change_alone_does_not_change_the_notation_tonic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_xml(directory, "signature-change.musicxml", SIGNATURE_CHANGE_XML)
            events = [row for row in rows(core.musicxml_to_jianpu_text(path))
                      if row["type"] == "event"]
        self.assertEqual(["1", "5"], [row["pitches"] for row in events])

    def test_fixed_mode_maps_c4_to_one_and_d4_to_two_without_a_key_signature(self):
        fixed_xml = NO_KEY_XML.replace(
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>',
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration></note>'
            '<note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration></note>',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_xml(directory, "fixed.musicxml", fixed_xml)
            events = [row for row in rows(core.musicxml_to_jianpu_text(path, mode="fixed"))
                      if row["type"] == "event"]
        self.assertEqual(["1", "2"], [row["pitches"] for row in events])

    def test_event_jsonl_preserves_parts_chords_ties_rests_and_escaped_lyrics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_xml(directory, "events.musicxml", EVENTS_XML)
            events = [row for row in rows(core.musicxml_to_jianpu_text(path))
                      if row["type"] == "event"]

        chord = events[0]
        self.assertEqual(("chord", ["1", "3"], ["start", "none"]), (
            chord["kind"],
            chord["pitches"],
            chord["ties"],
        ))
        self.assertEqual("星\t光\n夜", chord["lyrics"][0]["text"])
        self.assertEqual(
            [("1", "rest", "2"), ("2", "note", "0"), ("2", "note", "1"), ("2", "rest", "2")],
            [(row["measure"], row["kind"], row["onset"]) for row in events[2:]],
        )
        self.assertEqual(["stop"], events[1]["ties"])
        self.assertTrue(all(row["duration"] != "0" for row in events))

    def test_all_five_satbb_parts_and_source_events_are_retained(self):
        converted = rows(core.musicxml_to_jianpu_text(SATBB, mode="fixed"))
        self.assertEqual(
            ["P-S", "P-A", "P-T", "P-BR", "P-B"],
            [row["part"] for row in converted if row["type"] == "part"],
        )
        events = [row for row in converted if row["type"] == "event"]
        self.assertTrue(any(row["kind"] == "rest" for row in events))
        self.assertTrue(any(row["kind"] == "chord" and len(row["pitches"]) == 2 for row in events))
        self.assertTrue(any(row["lyrics"] for row in events))
        self.assertTrue(any("start" in row["ties"] for row in events))

    def test_movable_without_key_or_tonic_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_xml(directory, "no-key.musicxml", NO_KEY_XML)
            with self.assertRaisesRegex(ValueError, "missing_tonic"):
                core.musicxml_to_jianpu_text(path, mode="movable")
            fixed = core.musicxml_to_jianpu_text(path, mode="fixed")
        self.assertTrue(any(row["type"] == "event" for row in rows(fixed)))

    def test_invalid_timeline_is_rejected_before_midi_output_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_xml(directory, "invalid.musicxml", INVALID_TIMELINE_XML)
            output = Path(directory) / "not-created" / "result.mid"
            with self.assertRaisesRegex(ValueError, "measure_overflow"):
                core.musicxml_to_midi(source, output)
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())

    def test_midi_uses_exact_tuplet_positions_and_merges_only_tied_pitches(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_xml(directory, "events.musicxml", EVENTS_XML)
            midi_path = core.musicxml_to_midi(
                source,
                Path(directory) / "events.mid",
                core.ConvertOptions(bpm=120),
            )
            midi = pretty_midi.PrettyMIDI(str(midi_path))

        instrument = midi.instruments[0]
        c4 = [note for note in instrument.notes if note.pitch == 60]
        d4 = [note for note in instrument.notes if note.pitch == 62]
        e4 = [note for note in instrument.notes if note.pitch == 64]
        self.assertEqual(1, len(c4))
        self.assertAlmostEqual(0.0, c4[0].start, places=5)
        self.assertAlmostEqual(1.0, c4[0].end, places=5)
        self.assertEqual(2, len(d4))
        self.assertEqual([(2.0, 2.5), (2.5, 3.0)], [
            (round(note.start, 5), round(note.end, 5)) for note in d4
        ])
        self.assertEqual(1, len(e4))
        self.assertAlmostEqual(0.5, e4[0].end, places=5)

    def test_midi_places_triplets_after_cumulative_measure_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            midi_path = core.musicxml_to_midi(
                G_MAJOR,
                Path(directory) / "triplets.mid",
                core.ConvertOptions(bpm=120),
            )
            midi = pretty_midi.PrettyMIDI(str(midi_path))

        notes = midi.instruments[0].notes
        d5 = next(note for note in notes if note.pitch == 74)
        e5 = next(note for note in notes if note.pitch == 76)
        self.assertAlmostEqual(2.0, d5.start, places=5)
        self.assertAlmostEqual(2.0 + 1 / 6, d5.end, places=5)
        self.assertAlmostEqual(2.0 + 1 / 6, e5.start, places=5)


if __name__ == "__main__":
    unittest.main()
