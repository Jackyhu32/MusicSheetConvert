"""Complex-score E2E test: grand staff (two hands) / multiple key signatures / chords
all go through MusicXML/MIDI/jianpu/PNG.

Dependencies:
    - music21, pretty_midi (always)
    - MuseScore 4 CLI (for PNG rendering and round-trip tests)
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.music_convert import core
from src.music_convert.advanced import (
    NoteSpec,
    build_bach_prelude_c_major,
    build_chord_progression,
    build_grand_staff,
    build_key_demonstration,
    write_score,
)
from src.render import find_musescore, midi_to_musicxml, musicxml_to_png


def _jianpu_events(xml_path: Path) -> list[dict]:
    """Parse event rows from the converter's JSONL output."""
    rows = [
        json.loads(line)
        for line in core.musicxml_to_jianpu_text(xml_path).splitlines()
    ]
    return [row for row in rows if row["type"] == "event"]


def _has_musescore() -> bool:
    return find_musescore() is not None


def test_grand_staff_in_each_key(tmp: Path) -> None:
    """Build a grand-staff score in every key signature, verify MusicXML/MIDI/jianpu are produced."""
    from music21 import pitch as m21pitch

    from src.music_convert.advanced import KEY_PRESETS
    for key_name in KEY_PRESETS:
        tonic = KEY_PRESETS[key_name].tonic
        t = m21pitch.Pitch(tonic.nameWithOctave)
        rh = [[NoteSpec([t.transpose(j).nameWithOctave], 1.0) for j in (0, 2, 4, 5)],
              [NoteSpec([t.transpose(j).nameWithOctave], 1.0) for j in (7, 9, 11, 12)]]
        lh = [[NoteSpec([f"{tonic.name}3"], 4.0)] for _ in range(2)]
        score = build_grand_staff(rh, lh, key_name=key_name,
                                  title=f"Grand Staff in {key_name}")
        paths = write_score(score, tmp / key_name, f"gs_{key_name}")
        assert paths["musicxml"].exists()
        assert paths["midi"].exists() and paths["midi"].stat().st_size > 0

        events = _jianpu_events(paths["musicxml"])
        assert len(events) == 10, f"{key_name}: expected 10 note events, got {len(events)}"
        pitch_tokens = [event["pitches"] for event in events]
        assert all(isinstance(token, str) for token in pitch_tokens)
        assert all(
            re.fullmatch(r"[#b]?[1-7](?:\^[1-9]|v[1-9])?", token)
            for token in pitch_tokens
        ), f"{key_name}: invalid Jianpu event pitches: {pitch_tokens}"
        print(f"  {key_name:3} JSONL events: {len(events)}")


def test_chord_progression_with_7ths(tmp: Path) -> None:
    """Cmaj7 - Dm7 - G7 - Cmaj7 7th-chord progression."""
    chords = [
        ["C4", "E4", "G4", "B4"],
        ["D4", "F4", "A4", "C5"],
        ["G3", "B3", "D4", "F4"],
        ["C4", "E4", "G4", "B4"],
    ]
    score = build_chord_progression(chords, key_name="C", title="ii-V-I with 7ths")
    paths = write_score(score, tmp / "chord7", "prog")
    events = _jianpu_events(paths["musicxml"])
    chord_events = [event for event in events if event["kind"] == "chord"]
    assert len(chord_events) == 4
    expected_pitches = [
        ["1", "3", "5", "7"],
        ["2", "4", "6", "1^1"],
        ["5v1", "7v1", "2", "4"],
        ["1", "3", "5", "7"],
    ]
    assert [event["pitches"] for event in chord_events] == expected_pitches
    assert all(isinstance(event["pitches"], list) for event in chord_events)
    print(f"  C major ii-V-I 7th chords: {len(chord_events)} chord events")


def test_key_demonstration_all_keys(tmp: Path) -> None:
    """Cover all 9 key signatures: C / G / D / F / Bb / Eb / Am / Em / Dm."""
    score = build_key_demonstration()
    paths = write_score(score, tmp / "keys", "demo")
    events = _jianpu_events(paths["musicxml"])
    print(f"  9 key signatures yield {len(events)} events")
    assert len(events) == 9 * 2
    assert all(event["kind"] == "chord" for event in events)


def test_render_png(tmp: Path) -> None:
    """Render a MusicXML to PNG via MuseScore."""
    if not _has_musescore():
        print("  [skip] MuseScore unavailable, skipping PNG render")
        return
    score = build_grand_staff(
        [[NoteSpec(["C4"], 1.0), NoteSpec(["D4"], 1.0),
          NoteSpec(["E4"], 1.0), NoteSpec(["F4"], 1.0)]],
        [[NoteSpec(["C3", "E3", "G3"], 4.0)]],
        key_name="C", title="Render Test"
    )
    paths = write_score(score, tmp / "render", "simple")
    out_png = tmp / "render" / "simple.png"
    musicxml_to_png(paths["musicxml"], out_png)
    assert out_png.exists() and out_png.stat().st_size > 1024
    print(f"  PNG render OK: {out_png.stat().st_size} bytes")


def test_bach_prelude(tmp: Path) -> None:
    """First 4 measures of Bach's Prelude in C major (the classic 8-note broken-chord pattern)."""
    score = build_bach_prelude_c_major()
    paths = write_score(score, tmp / "bach", "prelude_m1_m4")
    events = _jianpu_events(paths["musicxml"])
    note_chord_events = [
        event for event in events if event["kind"] in ("note", "chord")
    ]
    print(f"  Bach prelude 4 measures: {len(note_chord_events)} note/chord events")
    assert len(note_chord_events) == 40
    assert note_chord_events[0]["pitches"] == "1^1"


def test_round_trip_xml_midi_xml(tmp: Path) -> None:
    """MusicXML -> MIDI -> MusicXML roundtrip; verify the note sequence is preserved."""
    if not _has_musescore():
        print("  [skip] MuseScore unavailable, skipping roundtrip")
        return
    score = build_grand_staff(
        [[NoteSpec(["C4"], 1.0), NoteSpec(["D4"], 1.0),
          NoteSpec(["E4"], 1.0), NoteSpec(["F4"], 1.0)]],
        [[NoteSpec(["C3", "E3", "G3"], 4.0)]],
        key_name="C", title="Roundtrip Test",
    )
    paths = write_score(score, tmp / "rt", "rt")
    # MIDI -> MusicXML via MuseScore
    rt_xml = tmp / "rt" / "rt_from_midi.musicxml"
    midi_to_musicxml(paths["midi"], rt_xml)
    assert rt_xml.exists()
    # Compare
    from music21 import converter
    orig = list(converter.parse(str(paths["musicxml"])).recurse().notes)
    back = list(converter.parse(str(rt_xml)).recurse().notes)
    print(f"  Roundtrip: orig={len(orig)} notes, back={len(back)} notes")
    assert len(orig) == len(back)


def main() -> int:
    print("=== Complex-score E2E test ===")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("\n[1] Grand staff in 9 keys:")
        test_grand_staff_in_each_key(tmp)
        print("\n[2] ii-V-I 7th-chord progression:")
        test_chord_progression_with_7ths(tmp)
        print("\n[3] 9-key-signature demonstration:")
        test_key_demonstration_all_keys(tmp)
        print("\n[4] MuseScore PNG render:")
        test_render_png(tmp)
        print("\n[5] Bach C major prelude:")
        test_bach_prelude(tmp)
        print("\n[6] MusicXML -> MIDI -> MusicXML roundtrip:")
        test_round_trip_xml_midi_xml(tmp)
    print("\nALL E2E PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
