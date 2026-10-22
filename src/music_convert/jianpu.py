import re

from src.music_convert.model import Pitch


_STEPS = "CDEFGAB"
_NATURAL_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_MAJOR_INTERVALS = (0, 2, 4, 5, 7, 9, 11)
_TONIC_PATTERN = re.compile(r"^([A-G])([#b]?)$")


def _signed_accidental(pitch_class: int, natural_pitch_class: int) -> int:
    accidental = (pitch_class - natural_pitch_class) % 12
    return accidental if accidental <= 6 else accidental - 12


def _parse_tonic(tonic: str) -> tuple[str, int]:
    if not isinstance(tonic, str):
        raise ValueError("tonic must be a note name from A to G, optionally with # or b")
    match = _TONIC_PATTERN.fullmatch(tonic)
    if match is None:
        raise ValueError("tonic must be a note name from A to G, optionally with # or b")
    step, accidental = match.groups()
    return step, 1 if accidental == "#" else -1 if accidental == "b" else 0


def _relative_major(step: str, alter: int) -> tuple[str, int]:
    minor_step_index = _STEPS.index(step)
    major_step = _STEPS[(minor_step_index + 2) % len(_STEPS)]
    target_pitch_class = (
        _NATURAL_SEMITONES[step] + alter + 3
    ) % 12
    major_alter = _signed_accidental(
        target_pitch_class, _NATURAL_SEMITONES[major_step]
    )
    if abs(major_alter) > 2:
        raise ValueError("tonic spelling does not have a usable relative major")
    return major_step, major_alter


def map_pitch(
    pitch: Pitch,
    *,
    tonic: str | None = None,
    key_mode: str | None = None,
    notation: str = "movable",
) -> tuple[str, int]:
    """Map a spelled pitch to a jianpu degree and tonic-relative octave."""
    if notation not in ("movable", "fixed"):
        raise ValueError("notation must be 'movable' or 'fixed'")
    if key_mode is not None and key_mode not in ("major", "minor"):
        raise ValueError("key_mode must be 'major' or 'minor'")
    if not isinstance(pitch, Pitch):
        raise ValueError("pitch must be a Pitch")
    if not isinstance(pitch.step, str) or pitch.step not in _STEPS:
        raise ValueError("pitch.step must be a note name from A to G")
    if isinstance(pitch.alter, bool) or not isinstance(pitch.alter, int):
        raise ValueError("pitch.alter must be an integer")
    if isinstance(pitch.octave, bool) or not isinstance(pitch.octave, int):
        raise ValueError("pitch.octave must be an integer")

    if notation == "fixed":
        root_step, root_alter = "C", 0
        tonic_semitone = _NATURAL_SEMITONES[root_step] + root_alter
    else:
        if tonic is None or key_mode is None:
            raise ValueError("movable notation requires both tonic and key_mode")
        root_step, root_alter = _parse_tonic(tonic)
        if key_mode == "minor":
            minor_step = root_step
            minor_alter = root_alter
            tonic_semitone = _NATURAL_SEMITONES[minor_step] + minor_alter
            root_step, root_alter = _relative_major(minor_step, minor_alter)
        else:
            tonic_semitone = _NATURAL_SEMITONES[root_step] + root_alter

    root_pitch_class = (
        _NATURAL_SEMITONES[root_step] + root_alter
    ) % 12
    degree_index = (_STEPS.index(pitch.step) - _STEPS.index(root_step)) % len(_STEPS)
    degree_step = _STEPS[(_STEPS.index(root_step) + degree_index) % len(_STEPS)]
    expected_alter = _signed_accidental(
        (root_pitch_class + _MAJOR_INTERVALS[degree_index]) % 12,
        _NATURAL_SEMITONES[degree_step],
    )
    chromatic_alter = pitch.alter - expected_alter
    prefix = "#" * chromatic_alter if chromatic_alter > 0 else "b" * -chromatic_alter

    tonic_at_octave_four = 5 * 12 + tonic_semitone
    pitch_semitone = (
        (pitch.octave + 1) * 12
        + _NATURAL_SEMITONES[pitch.step]
        + pitch.alter
    )
    octave_offset = (pitch_semitone - tonic_at_octave_four) // 12
    return f"{prefix}{degree_index + 1}", octave_offset
