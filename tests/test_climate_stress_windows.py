from __future__ import annotations

from datetime import datetime, timedelta
import unittest

import select_climate_stress_windows as selector


class ClimateStressWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        weather_with_endpoint, _ = selector.load_and_validate_weather_range(
            selector.WEATHER_PATH,
            selector.FULL_START,
            selector.FULL_END,
            allow_terminal_hold=True,
        )
        cls.candidates = selector.build_candidates(weather_with_endpoint[:-1])

    def test_stress_window_selection_deterministic(self) -> None:
        first = selector.select_windows(self.candidates)
        second = selector.select_windows(self.candidates)
        self.assertEqual(first, second)
        self.assertEqual(
            [item["type"] for item in first],
            [
                "REFERENCE_JUNE",
                "HUMID_STRESS",
                "HOT_SOLAR_STRESS",
                "DRY_VPD_STRESS",
                "TRANSITION_MIXED",
            ],
        )

    def test_windows_are_complete_and_nonredundant(self) -> None:
        windows = selector.select_windows(self.candidates)
        intervals = []
        for item in windows:
            start = datetime.fromisoformat(str(item["start_timestamp"]))
            end = datetime.fromisoformat(str(item["end_timestamp"]))
            self.assertEqual(end - start, timedelta(hours=719))
            self.assertEqual(item["hours"], 720)
            intervals.append((start, end))
        for index, (left_start, left_end) in enumerate(intervals):
            for right_start, right_end in intervals[index + 1 :]:
                overlap_start = max(left_start, right_start)
                overlap_end = min(left_end, right_end)
                overlap = (
                    0
                    if overlap_end < overlap_start
                    else int((overlap_end - overlap_start).total_seconds() // 3600) + 1
                )
                self.assertLessEqual(overlap / 720, selector.MAX_OVERLAP_FRACTION)


if __name__ == "__main__":
    unittest.main()
