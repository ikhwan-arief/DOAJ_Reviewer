from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from doaj_reviewer.golden import (
    DEFAULT_BASE_SUBMISSION,
    DEFAULT_CASES_PATH,
    DEFAULT_RULESET_PATH,
    load_case_definitions,
    run_golden_dataset,
)


class GoldenDatasetTests(unittest.TestCase):
    def test_case_definitions_are_valid(self) -> None:
        dataset = load_case_definitions(DEFAULT_CASES_PATH)
        self.assertEqual(dataset.get("dataset_id"), "doaj.golden.v1")
        self.assertEqual(dataset.get("version"), "1.0.0")
        cases = dataset.get("cases", [])
        self.assertIsInstance(cases, list)
        self.assertGreaterEqual(len(cases), 10)

    def test_golden_dataset_matches_expected_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "golden-out"
            report = run_golden_dataset(
                output_dir=out_dir,
                cases_path=DEFAULT_CASES_PATH,
                ruleset_path=DEFAULT_RULESET_PATH,
                base_submission_path=DEFAULT_BASE_SUBMISSION,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["scenario_count"], report["matched_count"])
            self.assertTrue((out_dir / "golden-report.json").exists())
            self.assertTrue((out_dir / "golden-report.md").exists())
            self.assertTrue((out_dir / "G1_PASS_BASELINE" / "review-summary.json").exists())
            self.assertTrue((out_dir / "G7_FAIL_REVIEWER_COMPOSITION" / "assertion-result.json").exists())
            self.assertTrue((out_dir / "G9_FAIL_ENDOGENY_ISSUE_OVER_THRESHOLD" / "endogeny-result.json").exists())


if __name__ == "__main__":
    unittest.main()
