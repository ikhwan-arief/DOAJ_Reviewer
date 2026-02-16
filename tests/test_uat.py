from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from doaj_reviewer.uat import (
    DEFAULT_BASE_SUBMISSION,
    DEFAULT_RULESET_PATH,
    build_uat_scenarios,
    run_uat_scenarios,
)


class UATRunnerTests(unittest.TestCase):
    def test_build_uat_scenarios_has_expected_targets(self) -> None:
        import json

        with DEFAULT_BASE_SUBMISSION.open("r", encoding="utf-8") as handle:
            base_submission = json.load(handle)

        scenarios = build_uat_scenarios(base_submission)
        self.assertEqual(len(scenarios), 3)
        expected = {item["expected_overall"] for item in scenarios}
        self.assertEqual(expected, {"pass", "need_human_review", "fail"})

    def test_run_uat_scenarios_generates_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "uat-out"
            report = run_uat_scenarios(
                output_dir=out_dir,
                ruleset_path=DEFAULT_RULESET_PATH,
                base_submission_path=DEFAULT_BASE_SUBMISSION,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["scenario_count"], 3)
            self.assertEqual(report["matched_count"], 3)
            self.assertTrue((out_dir / "uat-report.json").exists())
            self.assertTrue((out_dir / "uat-report.md").exists())
            self.assertTrue((out_dir / "S1_PASS_BASELINE" / "review-summary.txt").exists())
            self.assertTrue((out_dir / "S2_NEED_HUMAN_WAF" / "review-summary.json").exists())
            self.assertTrue((out_dir / "S3_FAIL_REVIEWER_COMPOSITION" / "endogeny-result.json").exists())


if __name__ == "__main__":
    unittest.main()

