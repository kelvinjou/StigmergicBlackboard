import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis.ttl_diff import TTLDiffAnalysis
from PrunedReconstruction.benchmark_runs import (
    BENCHMARK_COLUMNS,
    append_result,
    dataset_paths,
    normalize_sparql_batch,
    run_one_benchmark,
    should_terminate_for_api_error,
    validate_sparql_insert_only,
)


class BenchmarkHygieneTests(unittest.TestCase):
    def test_completed_rows_are_appended_immediately(self):
        temp_dir = Path(tempfile.mkdtemp())
        output_csv = temp_dir / "benchmark.csv"
        first = {
            "run_id": "first",
            "experiment_type": "agent",
            "output_valid": True,
        }
        second = {
            "run_id": "second",
            "experiment_type": "baseline",
            "output_valid": True,
        }

        append_result(output_csv, first)
        with output_csv.open(newline="", encoding="utf-8") as input_file:
            rows_after_first = list(csv.DictReader(input_file))

        append_result(output_csv, second)
        with output_csv.open(newline="", encoding="utf-8") as input_file:
            rows_after_second = list(csv.DictReader(input_file))

        self.assertEqual(len(rows_after_first), 1)
        self.assertEqual(len(rows_after_second), 2)
        self.assertEqual(rows_after_second[0]["run_id"], "first")
        self.assertEqual(rows_after_second[1]["run_id"], "second")
        self.assertEqual(
            list(rows_after_second[0]),
            BENCHMARK_COLUMNS,
        )

    def test_rate_limit_and_timeout_errors_are_terminal(self):
        class RateLimitError(Exception):
            status_code = 429

        class APITimeoutError(Exception):
            pass

        self.assertTrue(
            should_terminate_for_api_error(
                RateLimitError(
                    "Error code: 429 - Too Many Requests"
                )
            )
        )
        self.assertTrue(
            should_terminate_for_api_error(APITimeoutError("timed out"))
        )
        self.assertFalse(
            should_terminate_for_api_error(ValueError("invalid plan"))
        )

    def test_terminal_api_error_escapes_without_producing_a_row(self):
        class RateLimitError(Exception):
            status_code = 429

        with patch(
            "PrunedReconstruction.benchmark_runs.run_baseline",
            side_effect=RateLimitError(
                "Error code: 429 - {'title': 'Too Many Requests'}"
            ),
        ):
            with self.assertRaises(RateLimitError):
                run_one_benchmark(
                    dataset_root="dataset",
                    experiment_type="baseline",
                    community="Task",
                    model="test",
                    max_turns=1,
                    run_id="rate-limited",
                )

    def test_all_methods_share_inputs_and_keep_unique_outputs(self):
        methods = ("agent", "agent_no_traversal", "baseline", "sparql")
        paths = {
            method: dataset_paths(
                "dataset",
                method,
                "Task",
                "trial-1",
            )
            for method in methods
        }

        for input_key in ("modified_ttl", "summary", "detached_ttl"):
            self.assertEqual(
                len({str(value[input_key]) for value in paths.values()}),
                1,
            )

        self.assertEqual(
            len({str(value["output_ttl"]) for value in paths.values()}),
            len(methods),
        )
        self.assertTrue(
            all(
                value["output_ttl"].name == "reinserted_trial-1.ttl"
                for value in paths.values()
            )
        )

    def test_sparql_policy_only_accepts_insert_data(self):
        accepted = validate_sparql_insert_only(
            "INSERT DATA { <urn:a> <urn:b> <urn:c> . }"
        )
        deleted = validate_sparql_insert_only(
            "DELETE DATA { <urn:a> <urn:b> <urn:c> . }"
        )
        modified = validate_sparql_insert_only(
            "INSERT { <urn:a> <urn:b> <urn:c> . } WHERE {}"
        )
        shorthand = validate_sparql_insert_only(
            normalize_sparql_batch(
                "INSERT { <urn:a> <urn:b> <urn:c> . }"
            )
        )

        self.assertTrue(accepted["insert_only_valid"])
        self.assertFalse(deleted["insert_only_valid"])
        self.assertFalse(modified["insert_only_valid"])
        self.assertFalse(shorthand["insert_only_valid"])

    def test_failed_rows_are_not_scored(self):
        temp_dir = Path(tempfile.mkdtemp())
        benchmark_csv = temp_dir / "benchmark.csv"
        diff_csv = temp_dir / "diff.csv"
        summary_csv = temp_dir / "summary.csv"
        base = temp_dir / "base.ttl"
        ground_truth = temp_dir / "ground_truth.ttl"
        reconstructed = temp_dir / "reconstructed.ttl"

        base.write_text(
            "<urn:base> <urn:type> <urn:Base> .",
            encoding="utf-8",
        )
        ground_truth.write_text(
            "<urn:new> <urn:type> <urn:Class> .",
            encoding="utf-8",
        )
        reconstructed.write_text(
            (
                "<urn:base> <urn:type> <urn:Base> .\n"
                "<urn:new> <urn:type> <urn:Class> ."
            ),
            encoding="utf-8",
        )

        fieldnames = [
            "run_id",
            "community_pruned",
            "model",
            "experiment_type",
            "detached_ground_truth_ttl_path",
            "output_ttl_path",
            "modified_original_ttl_path",
            "elapsed_seconds",
            "total_tokens",
            "ttl_syntax_valid",
            "sparql_query_valid",
            "sparql_insert_only_valid",
            "execution_success",
            "output_valid",
            "scoring_eligible",
            "failure_type",
            "error",
        ]
        with benchmark_csv.open("w", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "run_id": "valid",
                    "community_pruned": "Task",
                    "model": "test",
                    "experiment_type": "baseline",
                    "detached_ground_truth_ttl_path": ground_truth,
                    "output_ttl_path": reconstructed,
                    "modified_original_ttl_path": base,
                    "elapsed_seconds": 2,
                    "total_tokens": 100,
                    "ttl_syntax_valid": True,
                    "execution_success": True,
                    "output_valid": True,
                    "scoring_eligible": True,
                }
            )
            writer.writerow(
                {
                    "run_id": "failed",
                    "community_pruned": "Task",
                    "model": "test",
                    "experiment_type": "baseline",
                    "detached_ground_truth_ttl_path": ground_truth,
                    "output_ttl_path": temp_dir / "stale-or-missing.ttl",
                    "modified_original_ttl_path": base,
                    "elapsed_seconds": 4,
                    "total_tokens": 50,
                    "ttl_syntax_valid": False,
                    "execution_success": False,
                    "output_valid": False,
                    "scoring_eligible": False,
                    "failure_type": "api_timeout",
                    "error": "APITimeoutError",
                }
            )

        analysis = TTLDiffAnalysis()
        rows = analysis.run_agent_diffs(benchmark_csv, diff_csv)
        summary = analysis.analyze_scores_by_experiment(
            diff_csv,
            summary_csv,
        )[0]

        self.assertEqual(rows[0]["triple_f1"], 1)
        self.assertNotIn("triple_f1", rows[1])
        self.assertEqual(summary["attempted_trials"], 2)
        self.assertEqual(summary["scored_trials"], 1)
        self.assertEqual(summary["failed_trials"], 1)
        self.assertEqual(summary["triple_precision_mean"], 1)
        self.assertEqual(summary["triple_precision_attempt_mean"], 0.5)
        self.assertEqual(summary["triple_recall_mean"], 1)
        self.assertEqual(summary["triple_recall_attempt_mean"], 0.5)
        self.assertEqual(summary["triple_f1_mean"], 1)
        self.assertEqual(summary["triple_f1_attempt_mean"], 0.5)
        self.assertEqual(summary["total_tokens_mean"], 75)
        self.assertEqual(summary["elapsed_seconds_mean"], 3)


if __name__ == "__main__":
    unittest.main()
