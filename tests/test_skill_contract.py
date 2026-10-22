import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.main import build_parser  # isort: skip


SKILL_PATH = ROOT / "skill.md"


def _read_skill():
    return SKILL_PATH.read_text(encoding="utf-8")


def _frontmatter_match(text):
    match = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", text, re.DOTALL)
    if match is None:
        raise AssertionError("skill.md must start with YAML frontmatter delimited by ---")
    return match


def _parse_frontmatter(text):
    match = _frontmatter_match(text)
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        raise AssertionError(f"skill.md frontmatter must be valid YAML: {error}") from error
    return metadata


def _option_action(parser, option):
    action = parser._option_string_actions.get(option)
    if action is None:
        raise AssertionError(f"CLI parser must define {option}")
    return action


class SkillMetadataContractTests(unittest.TestCase):
    def test_frontmatter_has_valid_required_skill_metadata(self):
        skill = _read_skill()
        frontmatter = _frontmatter_match(skill)
        metadata = _parse_frontmatter(skill)

        self.assertLessEqual(len(frontmatter.group(0)), 1024)
        self.assertIsInstance(metadata, dict)
        self.assertIsInstance(metadata.get("name"), str)
        self.assertRegex(metadata["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertEqual("staff-to-jianpu", metadata["name"])
        self.assertLessEqual(len(metadata["name"]), 64)
        self.assertIsInstance(metadata.get("description"), str)
        self.assertTrue(metadata["description"].startswith("Use when"))
        self.assertTrue(metadata["description"].strip())
        self.assertLessEqual(len(metadata["description"]), 1024)


class SkillTextContractTests(unittest.TestCase):
    REQUIRED_PHRASES = (
        "Movable-do is the default.",
        "Fixed-do is available only when explicitly requested.",
        "In minor keys, the tonic is scale degree 6.",
        "Transcribe only voices present in the source score.",
        "Never invent a melody or voice.",
        "A key-signature change alone does not prove modulation.",
        "Disclose uncertain readings; do not silently guess.",
        "Offer review-only output when pitch reading is uncertain.",
        "Preserve source transcription in editable MusicXML.",
        (
            "Jianpu mapping uses sounding pitch while retaining written pitch "
            "for source audit."
        ),
    )

    FORBIDDEN_PATTERNS = (
        r"key[- ]signature change(?:s)? alone (?:prove|proves|confirm|confirms) modulation",
        r"when the key signature changes mid-piece, mark .* at the modulation point",
        r"male voices are (?:always )?(?:notated|written|shifted) one octave (?:higher|up)",
        r"always add a footnote|mandatory footnote",
        r"publication[- ]ready",
        r"custom formats|user-specified formats",
    )

    def test_skill_states_unambiguous_accuracy_and_review_rules(self):
        skill = _read_skill()
        for phrase in self.REQUIRED_PHRASES:
            with self.subTest(required_phrase=phrase):
                self.assertIn(phrase, skill)

    def test_skill_does_not_repeat_disallowed_legacy_claims(self):
        skill = _read_skill()
        for pattern in self.FORBIDDEN_PATTERNS:
            with self.subTest(forbidden_pattern=pattern):
                self.assertNotRegex(skill, re.compile(pattern, re.IGNORECASE))

    def test_skill_documents_only_real_cli_flags_and_formats(self):
        skill = _read_skill()
        cli_section = re.search(
            r"(?ms)^## Supported CLI\s*\n(.*?)(?=^## |\Z)", skill
        )
        self.assertIsNotNone(cli_section, "skill.md must include ## Supported CLI")
        if cli_section is None:
            return

        cli_contract = cli_section.group(1)
        parser = build_parser()
        defaults = parser.parse_args(["score.musicxml"])
        mode_action = _option_action(parser, "--mode")
        tonic_action = _option_action(parser, "--tonic")
        formats_action = _option_action(parser, "--formats")
        converter_globals = getattr(formats_action.type, "__globals__", {})
        supported_formats = converter_globals.get("_SUPPORTED_FORMATS")
        self.assertIsNotNone(
            supported_formats,
            "the --formats converter must expose _SUPPORTED_FORMATS",
        )
        if supported_formats is None:
            return

        for option in ("--mode", "--tonic", "--formats"):
            with self.subTest(option=option):
                self.assertIn(option, cli_contract)

        supported_modes = tuple(mode_action.choices or ())
        expected_cli_text = (
            f"Supported modes: {', '.join(supported_modes)}.",
            f"Default mode: {defaults.mode}.",
            f"Default tonic: {defaults.tonic if defaults.tonic is not None else 'none'}.",
            f"Default formats: {', '.join(defaults.formats)}.",
            f"Supported formats: {', '.join(sorted(supported_formats))}.",
        )
        self.assertEqual(mode_action.default, defaults.mode)
        self.assertEqual(tonic_action.default, defaults.tonic)
        self.assertEqual(formats_action.default, defaults.formats)

        for required_text in expected_cli_text:
            with self.subTest(required_text=required_text):
                self.assertIn(required_text, cli_contract)

        for format_name in sorted(supported_formats):
            parsed = parser.parse_args(
                ["score.musicxml", "--formats", format_name]
            )
            with self.subTest(format_name=format_name):
                self.assertEqual((format_name,), parsed.formats)
                self.assertIn(format_name, cli_contract)

        self.assertNotRegex(
            cli_contract, re.compile(r"\bcustom formats\b", re.IGNORECASE)
        )


class CliParserContractTests(unittest.TestCase):
    def test_parser_defaults_and_supported_notation_arguments(self):
        parser = build_parser()
        defaults = parser.parse_args(["score.musicxml"])

        self.assertEqual(_option_action(parser, "--mode").default, defaults.mode)
        self.assertEqual(_option_action(parser, "--tonic").default, defaults.tonic)
        self.assertEqual(_option_action(parser, "--formats").default, defaults.formats)

        selected = parser.parse_args(
            [
                "score.musicxml",
                "--mode",
                "fixed",
                "--tonic",
                "F#",
                "--formats",
                "pdf,musicxml",
            ]
        )
        self.assertEqual("fixed", selected.mode)
        self.assertEqual("F#", selected.tonic)
        self.assertEqual(("pdf", "musicxml"), selected.formats)

    def test_parser_rejects_unsupported_mode_and_format_values(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["score.musicxml", "--mode", "custom"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["score.musicxml", "--formats", "custom"])


if __name__ == "__main__":
    unittest.main()
