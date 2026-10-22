import unittest

from src.music_convert.jianpu import map_pitch
from src.music_convert.model import Pitch


class JianpuMappingTests(unittest.TestCase):
    def test_movable_major_maps_tonic_to_one(self):
        self.assertEqual(
            ("1", 0),
            map_pitch(Pitch("G", 0, 4), tonic="G", key_mode="major"),
        )

    def test_movable_minor_uses_relative_major_frame(self):
        self.assertEqual(
            ("6", 0),
            map_pitch(Pitch("A", 0, 4), tonic="A", key_mode="minor"),
        )

    def test_fixed_do_uses_c_as_one_independent_of_key(self):
        self.assertEqual(("1", 0), map_pitch(Pitch("C", 0, 4), notation="fixed"))
        self.assertEqual(("2", 0), map_pitch(Pitch("D", 0, 4), notation="fixed"))

    def test_key_signature_is_accounted_for_without_changing_spelling(self):
        self.assertEqual(
            ("7", -1),
            map_pitch(Pitch("F", 1, 4), tonic="G", key_mode="major"),
        )
        self.assertEqual(
            ("#4", 0),
            map_pitch(Pitch("F", 1, 4), tonic="C", key_mode="major"),
        )
        self.assertEqual(
            ("b7", 0),
            map_pitch(Pitch("B", -1, 4), tonic="C", key_mode="major"),
        )

    def test_enharmonic_spellings_keep_distinct_degrees(self):
        self.assertEqual(
            ("#4", 0),
            map_pitch(Pitch("F", 1, 4), tonic="C", key_mode="major"),
        )
        self.assertEqual(
            ("b5", 0),
            map_pitch(Pitch("G", -1, 4), tonic="C", key_mode="major"),
        )

    def test_written_enharmonic_tonics_anchor_their_own_octave(self):
        self.assertEqual(
            ("1", 0),
            map_pitch(Pitch("B", 1, 4), tonic="B#", key_mode="major"),
        )
        self.assertEqual(
            ("1", 0),
            map_pitch(Pitch("C", -1, 4), tonic="Cb", key_mode="major"),
        )

    def test_octave_offset_uses_absolute_pitch_not_spelling_position(self):
        self.assertEqual(
            ("#7", 0),
            map_pitch(Pitch("B", 1, 3), tonic="C", key_mode="major"),
        )
        self.assertEqual(
            ("1", 0),
            map_pitch(Pitch("C", 0, 4), tonic="C", key_mode="major"),
        )

    def test_non_string_pitch_step_raises_value_error(self):
        with self.assertRaises(ValueError):
            map_pitch(Pitch(1, 0, 4), notation="fixed")

    def test_octave_offset_is_relative_to_tonic_octave(self):
        self.assertEqual(
            ("1", 1),
            map_pitch(Pitch("G", 0, 5), tonic="G", key_mode="major"),
        )
        self.assertEqual(
            ("1", -1),
            map_pitch(Pitch("G", 0, 3), tonic="G", key_mode="major"),
        )

    def test_movable_notation_requires_tonic_and_key_mode(self):
        for options in ({}, {"tonic": "C"}, {"key_mode": "major"}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    map_pitch(Pitch("C", 0, 4), **options)

    def test_invalid_notation_key_mode_tonic_and_pitch_are_rejected(self):
        with self.assertRaises(ValueError):
            map_pitch(Pitch("C", 0, 4), notation="major")
        with self.assertRaises(ValueError):
            map_pitch(
                Pitch("C", 0, 4), tonic="C", key_mode="fixed", notation="movable"
            )
        with self.assertRaises(ValueError):
            map_pitch(Pitch("C", 0, 4), tonic="H", key_mode="major")
        with self.assertRaises(ValueError):
            map_pitch(Pitch("H", 0, 4), notation="fixed")


if __name__ == "__main__":
    unittest.main()
