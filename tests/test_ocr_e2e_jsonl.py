import json
import unittest

import ocr_e2e


def event_row(kind="note", pitches="1", **overrides):
    row = {
        "type": "event",
        "part": "P1",
        "measure": "1",
        "staff": "1",
        "voice": "1",
        "onset": "0",
        "duration": "1",
        "kind": kind,
        "pitches": pitches,
        "written_pitches": ["C4"],
        "ties": ["none"],
        "lyrics": [],
        "grace": False,
    }
    row.update(overrides)
    return row


def event_json(kind="note", pitches="1", **overrides):
    return json.dumps(event_row(kind, pitches, **overrides))


class JianpuJsonlValidationTests(unittest.TestCase):
    def test_accepts_note_and_chord_events_with_valid_pitch_tokens(self):
        samples = (
            '{"type":"part","part":"P1","name":"Piano"}\n'
            + event_json("note", "1^1"),
            '{"type":"part","part":"P1","name":"Piano"}\n'
            + event_json("chord", ["1", "3", "5"]),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_accepts_valid_multi_token_chord(self):
        ocr_e2e._validate_jianpu_jsonl(event_json("chord", ["1", "b3", "5^12"]))

    def test_rejects_part_metadata_and_rest_rows_without_pitched_events(self):
        samples = (
            '{"type":"part","part":"P1","name":"Piano"}',
            '{"type":"metadata","count":123}',
            event_json("rest", "0"),
            '{"type":"part","part":"P1","name":"Piano"}\n'
            + event_json("rest", "0"),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl), self.assertRaises(ValueError):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_unknown_row_type_and_event_kind(self):
        samples = (
            '{"type":"metadata","count":123}',
            event_json("unknown", "1"),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl), self.assertRaises(ValueError):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_part_row_missing_required_string_field(self):
        jsonl = '{"type":"part","part":"P1"}\n' + event_json()
        with self.assertRaisesRegex(ValueError, "part.*name"):
            ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_part_rows_with_non_string_fields(self):
        samples = (
            '{"type":"part","part":1,"name":"Piano"}\n' + event_json(),
            '{"type":"part","part":"P1","name":null}\n' + event_json(),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl), self.assertRaisesRegex(
                ValueError, "part row.*string"
            ):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_event_missing_required_schema_field(self):
        row = event_row()
        del row["voice"]
        with self.assertRaisesRegex(ValueError, "event.*voice"):
            ocr_e2e._validate_jianpu_jsonl(json.dumps(row))

    def test_rejects_duplicate_object_keys_with_line_number(self):
        jsonl = '{"type":"part","part":"P1","name":"Piano"}\n'
        jsonl += '{"type":"event","type":"event"}'
        with self.assertRaisesRegex(ValueError, "line 2.*duplicate"):
            ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_invalid_rest_pitch(self):
        with self.assertRaisesRegex(ValueError, "rest.*pitches.*0"):
            ocr_e2e._validate_jianpu_jsonl(event_json("rest", "1"))

    def test_accepts_repeated_same_type_accidentals(self):
        samples = (
            event_json("note", "##1"),
            event_json("note", "bb3"),
            event_json("chord", ["##1", "bb3"]),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_mixed_accidentals(self):
        samples = ("#b1", "b#1")
        for pitch in samples:
            with self.subTest(pitch=pitch), self.assertRaises(ValueError):
                ocr_e2e._validate_jianpu_jsonl(event_json("note", pitch))

    def test_rejects_empty_or_invalid_note_pitch(self):
        for pitch in ("", "8", "1junk"):
            with self.subTest(pitch=pitch), self.assertRaises(ValueError):
                ocr_e2e._validate_jianpu_jsonl(event_json("note", pitch))

    def test_note_event_requires_exactly_one_pitch_token(self):
        with self.assertRaises(ValueError):
            ocr_e2e._validate_jianpu_jsonl(event_json("note", ["1", "3"]))

    def test_rejects_chord_with_any_invalid_pitch_token(self):
        samples = (
            event_json("chord", ["1", ""]),
            event_json("chord", ["1", "bogus"]),
            event_json("chord", []),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl), self.assertRaises(ValueError):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_accepts_multi_digit_octave_tokens(self):
        samples = (
            event_json("note", "1^12"),
            event_json("chord", ["1v10", "3^12"]),
        )
        for jsonl in samples:
            with self.subTest(jsonl=jsonl):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_nonfinite_constants_with_line_number(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            jsonl = (
                '{"type":"part","part":"P1","name":"Piano"}\n'
                + '{"type":"event","part":"P1",'
                + '"measure":"1","staff":"1","voice":"1",'
                + '"onset":"0","duration":"1","kind":"note",'
                + f'"pitches":{constant},"written_pitches":[],"ties":[],'
                + '"lyrics":[],"grace":false}'
            )
            with self.subTest(constant=constant), self.assertRaisesRegex(
                ValueError, r"line 2.*(constant|JSON)"
            ):
                ocr_e2e._validate_jianpu_jsonl(jsonl)

    def test_rejects_malformed_json(self):
        with self.assertRaises(ValueError):
            ocr_e2e._validate_jianpu_jsonl('{"type":"event",')


if __name__ == "__main__":
    unittest.main()
