import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from src.music_convert.musicxml_io import load_musicxml


class PageMergeTests(unittest.TestCase):
    fixtures = Path(__file__).parent / "fixtures"

    def load(self, name):
        return load_musicxml(self.fixtures / name)

    def test_page_fixtures_parse_as_five_uniquely_named_parts(self):
        for name in ("omr-page-1.musicxml", "omr-page-2.musicxml"):
            with self.subTest(page=name):
                page = self.load(name)
                self.assertEqual(5, len(page.parts))
                self.assertEqual(5, len({part.name.casefold() for part in page.parts}))
                self.assertEqual(1, len(page.measures))

    def test_merges_pages_in_input_order_with_reindexed_events_and_source_locations(self):
        from src.music_convert.musicxml_io import merge_page_models

        first = self.load("omr-page-1.musicxml")
        second = self.load("omr-page-2.musicxml")
        merged = merge_page_models([first, second])

        self.assertEqual(["1", "2"], [measure.number for measure in merged.measures])
        self.assertEqual([0, 1], [measure.index for measure in merged.measures])
        self.assertEqual(
            ["P-S", "P-A", "P-T", "P-BR", "P-B"],
            [part.id for part in merged.parts],
        )
        self.assertEqual(
            ["Soprano", "Alto", "Tenor", "Baritone", "Bass"],
            [part.name for part in merged.parts],
        )
        self.assertEqual(5, len({part.name.casefold() for part in merged.parts}))
        for part in merged.parts:
            self.assertEqual([0, 1], [event.measure_index for event in part.events])
            self.assertEqual(
                [(1, "8"), (2, "8")],
                [
                    (event.source_location.page, event.source_location.measure_number)
                    for event in part.events
                ],
            )

        alto_lyrics = [event.lyrics[0].text for event in merged.parts[1].events]
        self.assertEqual(["page-one", "page-two"], alto_lyrics)
        self.assertEqual(
            (0, "major", 4, 4),
            (
                merged.measures[1].fifths,
                merged.measures[1].mode,
                merged.measures[1].beats,
                merged.measures[1].beat_type,
            ),
        )

    def test_input_order_controls_concatenated_content(self):
        from src.music_convert.musicxml_io import merge_page_models

        merged = merge_page_models(
            [self.load("omr-page-2.musicxml"), self.load("omr-page-1.musicxml")]
        )
        alto = merged.parts[1].events
        self.assertEqual(["page-two", "page-one"], [event.lyrics[0].text for event in alto])
        self.assertEqual([1, 2], [event.source_location.page for event in alto])

    def test_merge_serializes_editable_musicxml_with_notation_and_reviewable_boundary_tie(self):
        from src.music_convert.musicxml_io import merge_page_models

        merged = merge_page_models(
            [self.load("omr-page-1.musicxml"), self.load("omr-page-2.musicxml")]
        )

        self.assertIsInstance(merged.source_musicxml, bytes)
        self.assertIn(b"score-partwise", merged.source_musicxml)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "merged.musicxml"
            path.write_bytes(merged.source_musicxml)
            round_trip = load_musicxml(path)

        self.assertEqual(5, len(round_trip.parts))
        self.assertEqual(2, len(round_trip.measures))
        self.assertEqual(
            [("start",), ("none",)],
            [event.pitch_ties for event in round_trip.parts[0].events],
        )
        self.assertEqual(
            [("start", "1"), ("stop", "1")],
            [event.slurs[0] for event in round_trip.parts[0].events]
        )
        self.assertEqual(
            ["page-one", "page-two"],
            [event.lyrics[0].text for event in round_trip.parts[1].events],
        )
        self.assertTrue(merged.requires_review)
        issue = next(
            issue
            for issue in merged.review_issues
            if issue.code == "page_boundary_tie_unresolved"
        )
        self.assertEqual((1, "8"), (issue.location.page, issue.location.measure_number))

    def test_rejects_renamed_part_on_second_page(self):
        from src.music_convert.musicxml_io import merge_page_models

        with self.assertRaises(ValueError):
            merge_page_models(
                [
                    self.load("omr-page-1.musicxml"),
                    self.load("omr-page-2-renamed-part.musicxml"),
                ]
            )

    def test_rejects_omitted_part_on_second_page(self):
        from src.music_convert.musicxml_io import merge_page_models

        with self.assertRaises(ValueError):
            merge_page_models(
                [
                    self.load("omr-page-1.musicxml"),
                    self.load("omr-page-2-omitted-part.musicxml"),
                ]
            )

    def test_rejects_duplicate_part_names(self):
        from src.music_convert.musicxml_io import merge_page_models

        page = self.load("omr-page-1.musicxml")
        page.parts[1].name = page.parts[0].name
        with self.assertRaises(ValueError):
            merge_page_models([page, self.load("omr-page-2.musicxml")])

    def test_rejects_same_parts_in_different_order(self):
        from src.music_convert.musicxml_io import merge_page_models

        first = self.load("omr-page-1.musicxml")
        second = copy.deepcopy(self.load("omr-page-2.musicxml"))
        second.parts.reverse()
        with self.assertRaises(ValueError):
            merge_page_models([first, second])

    def test_does_not_invent_unestablished_key_or_time_at_page_boundary(self):
        from src.music_convert.musicxml_io import merge_page_models

        first = self.load("omr-page-2.musicxml")
        second = copy.deepcopy(first)
        second.title = "No Context Page"
        second.measures = [
            replace(
                measure,
                fifths=None,
                mode=None,
                beats=None,
                beat_type=None,
            )
            for measure in second.measures
        ]
        merged = merge_page_models([first, second])
        self.assertEqual(
            [(None, None, None, None), (None, None, None, None)],
            [
                (measure.fifths, measure.mode, measure.beats, measure.beat_type)
                for measure in merged.measures
            ],
        )


if __name__ == "__main__":
    unittest.main()
