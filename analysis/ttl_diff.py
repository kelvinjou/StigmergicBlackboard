import csv
from statistics import mean, median, stdev
from pathlib import Path
from typing import Optional

from rdflib import Graph
from rdflib.compare import isomorphic



class TTLDiffAnalysis:
    def __init__(self):
        pass

    def ttlDiff(
        self,
        ground_truth_path: str,
        reinserted_path: str,
        base_path: Optional[str] = None,
    ):
        ground_truth = Graph()
        reinserted = Graph()

        ground_truth.parse(ground_truth_path, format="ttl")
        reinserted.parse(reinserted_path, format="ttl")

        ground_truth_triples = set(ground_truth)
        reinserted_triples = set(reinserted)
        base_triples = set()

        if base_path:
            base = Graph()
            base.parse(base_path, format="ttl")
            base_triples = set(base)
            reinserted_triples = reinserted_triples - base_triples

        shared = ground_truth_triples & reinserted_triples
        missing = ground_truth_triples - reinserted_triples
        extra = reinserted_triples - ground_truth_triples

        # Precision means: of the triples the method reinserted, how many were actually correct? (High precision means the method did not add many wrong or extra triples.)
        # High recall means the method recovered most of the missing community.
        # F1: combination of precision and recall (higher the better)
        precision = len(shared) / len(reinserted_triples) if reinserted_triples else 0
        recall = len(shared) / len(ground_truth_triples) if ground_truth_triples else 0

        if precision + recall:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0

        return {
            "ground_truth_triples": len(ground_truth_triples),
            "base_triples": len(base_triples),
            "reinserted_triples": len(reinserted_triples),
            "shared_triples": len(shared),
            "missing_triples": len(missing),
            "extra_triples": len(extra),
            "triple_precision": precision,
            "triple_recall": recall,
            "triple_f1": f1,
            "exact_graph_match": (
                ground_truth_triples == reinserted_triples
                if base_path
                else isomorphic(ground_truth, reinserted) # what is isomorphic here
            ),
        }

    def run_agent_diffs(
        self,
        benchmark_csv_path: str = "benchmark_results.csv",
        output_csv_path: str = "analysis/ttl_diff_results.csv",
    ):
        output_fields = [
            "run_id",
            "community_pruned",
            "model",
            "experiment_type",
            "elapsed_seconds",
            "total_tokens",
            "ttl_syntax_valid",
            "sparql_query_valid",
            "sparql_insert_only_valid",
            "execution_success",
            "output_valid",
            "scoring_eligible",
            "failure_type",
            "ground_truth_triples",
            "base_triples",
            "reinserted_triples",
            "shared_triples",
            "missing_triples",
            "extra_triples",
            "triple_precision",
            "triple_recall",
            "triple_f1",
            "exact_graph_match",
            "error",
        ]

        # comparing detached.ttl against actual inserted node (reinserted.ttl - modified_original.ttl)
        output_rows = []
        with open(benchmark_csv_path, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                # if row.get("experiment_type") != "agent":
                #     continue

                result_row = {
                    "run_id": row.get("run_id", ""),
                    "community_pruned": row.get("community_pruned", ""),
                    "model": row.get("model", ""),
                    "experiment_type": row.get("experiment_type", ""),
                    "elapsed_seconds": row.get("elapsed_seconds", ""),
                    "total_tokens": row.get("total_tokens", ""),
                    "ttl_syntax_valid": row.get(
                        "ttl_syntax_valid", ""
                    ),
                    "sparql_query_valid": row.get(
                        "sparql_query_valid", ""
                    ),
                    "sparql_insert_only_valid": row.get(
                        "sparql_insert_only_valid", ""
                    ),
                    "execution_success": row.get(
                        "execution_success", ""
                    ),
                    "output_valid": row.get("output_valid", ""),
                    "failure_type": row.get("failure_type", ""),
                    "error": (row.get("error") or "").strip(),
                }

                explicit_eligibility = (
                    row.get("scoring_eligible") or ""
                ).strip()
                if explicit_eligibility:
                    scoring_eligible = (
                        explicit_eligibility.lower() == "true"
                    )
                else:
                    # Backward compatibility for benchmark files created before
                    # scoring_eligible was recorded.
                    scoring_eligible = (
                        not result_row["error"]
                        and str(
                            row.get("ttl_syntax_valid", "")
                        ).lower()
                        != "false"
                        and (
                            row.get("experiment_type") != "sparql"
                            or str(
                                row.get("sparql_query_valid", "")
                            ).lower()
                            != "false"
                        )
                    )
                result_row["scoring_eligible"] = scoring_eligible

                # A failed benchmark may leave behind a stale or partial output.
                # Never calculate scores from an ineligible artifact.
                if scoring_eligible:
                    try:
                        metrics = self.ttlDiff(
                            row["detached_ground_truth_ttl_path"],
                            row["output_ttl_path"],
                            row["modified_original_ttl_path"],
                        )
                        result_row.update(metrics)
                    except Exception as exc:
                        result_row["scoring_eligible"] = False
                        result_row["failure_type"] = "analysis_error"
                        result_row["error"] = f"{type(exc).__name__}: {exc}"
                elif not result_row["error"]:
                    result_row["error"] = (
                        result_row["failure_type"]
                        or "benchmark_output_ineligible"
                    )

                output_rows.append(result_row)

        Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv_path, "w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=output_fields)
            writer.writeheader()
            writer.writerows(output_rows)

        return output_rows

    def analyze_scores_by_experiment(
        self,
        diff_results_csv_path: str = "analysis/ttl_diff_results.csv",
        output_csv_path: Optional[str] = "analysis/ttl_diff_score_summary.csv",
    ):
        score_columns = ["triple_precision", "triple_recall", "triple_f1"]
        resource_columns = ["total_tokens", "elapsed_seconds"]
        grouped_rows = {}

        with open(diff_results_csv_path, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                experiment_type = row.get("experiment_type", "")
                if not experiment_type:
                    continue

                grouped_rows.setdefault(experiment_type, []).append(row)

        summary_rows = []
        for experiment_type, rows in sorted(grouped_rows.items()):
            scored_rows = [
                row
                for row in rows
                if str(row.get("scoring_eligible", "")).lower() == "true"
                and not row.get("error")
            ]
            output_valid_rows = [
                row
                for row in rows
                if str(row.get("output_valid", "")).lower() == "true"
            ]
            shared_total = sum(
                int(row["shared_triples"]) for row in scored_rows
            )
            reinserted_total = sum(
                int(row["reinserted_triples"]) for row in scored_rows
            )
            ground_truth_total = sum(
                int(row["ground_truth_triples"]) for row in scored_rows
            )
            micro_precision = (
                shared_total / reinserted_total if reinserted_total else 0
            )
            micro_recall = (
                shared_total / ground_truth_total
                if ground_truth_total
                else 0
            )
            micro_f1 = (
                2
                * micro_precision
                * micro_recall
                / (micro_precision + micro_recall)
                if micro_precision + micro_recall
                else 0
            )
            summary_row = {
                "experiment_type": experiment_type,
                "attempted_trials": len(rows),
                "num_trials": len(scored_rows),
                "scored_trials": len(scored_rows),
                "failed_trials": len(rows) - len(scored_rows),
                "failure_rate": (
                    (len(rows) - len(scored_rows)) / len(rows)
                    if rows
                    else 0
                ),
                "output_valid_count": len(output_valid_rows),
                "output_valid_rate": (
                    len(output_valid_rows) / len(rows) if rows else 0
                ),
                "exact_match_count": sum(
                    row.get("exact_graph_match") == "True"
                    for row in scored_rows
                ),
                "exact_match_rate": (
                    sum(
                        row.get("exact_graph_match") == "True"
                        for row in scored_rows
                    )
                    / len(scored_rows)
                    if scored_rows
                    else 0
                ),
                "triple_micro_precision": micro_precision,
                "triple_micro_recall": micro_recall,
                "triple_micro_f1": micro_f1,
            }

            for column in score_columns:
                values = [
                    float(row[column])
                    for row in scored_rows
                    if row.get(column) != ""
                ]
                attempt_values = [
                    (
                        float(row[column])
                        if (
                            str(
                                row.get("scoring_eligible", "")
                            ).lower()
                            == "true"
                            and not row.get("error")
                            and row.get(column) not in {"", None}
                        )
                        else 0
                    )
                    for row in rows
                ]
                summary_row[f"{column}_mean"] = mean(values) if values else 0
                summary_row[f"{column}_attempt_mean"] = (
                    mean(attempt_values) if attempt_values else 0
                )
                summary_row[f"{column}_median"] = median(values) if values else 0
                summary_row[f"{column}_stdev"] = stdev(values) if len(values) > 1 else 0
                summary_row[f"{column}_min"] = min(values) if values else 0
                summary_row[f"{column}_max"] = max(values) if values else 0

            for column in resource_columns:
                values = [
                    float(row[column])
                    for row in rows
                    if row.get(column) not in {"", None}
                ]
                summary_row[f"{column}_mean"] = mean(values) if values else 0
                summary_row[f"{column}_median"] = median(values) if values else 0
                summary_row[f"{column}_stdev"] = (
                    stdev(values) if len(values) > 1 else 0
                )

            summary_rows.append(summary_row)

        if output_csv_path:
            output_fields = [
                "experiment_type",
                "attempted_trials",
                "num_trials",
                "scored_trials",
                "failed_trials",
                "failure_rate",
                "output_valid_count",
                "output_valid_rate",
                "exact_match_count",
                "exact_match_rate",
                "triple_micro_precision",
                "triple_micro_recall",
                "triple_micro_f1",
            ]
            for column in score_columns:
                output_fields.extend(
                    [
                        f"{column}_mean",
                        f"{column}_attempt_mean",
                        f"{column}_median",
                        f"{column}_stdev",
                        f"{column}_min",
                        f"{column}_max",
                    ]
                )
            for column in resource_columns:
                output_fields.extend(
                    [
                        f"{column}_mean",
                        f"{column}_median",
                        f"{column}_stdev",
                    ]
                )

            Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_csv_path, "w", newline="") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=output_fields)
                writer.writeheader()
                writer.writerows(summary_rows)

        return summary_rows


if __name__ == "__main__":
    diff = TTLDiffAnalysis()
    rows = diff.run_agent_diffs()
    for row in rows:
        print(
            f"{row['community_pruned']} ({row['experiment_type']}): "
            f"precision={row.get('triple_precision', '')}, "
            f"recall={row.get('triple_recall', '')}, "
            f"f1={row.get('triple_f1', '')}, "
            f"exact={row.get('exact_graph_match', '')}, "
            f"error={row.get('error', '')}"
        )

    print()
    for row in diff.analyze_scores_by_experiment():
        print(
            f"{row['experiment_type']}: "
            f"precision_attempt_mean="
            f"{row['triple_precision_attempt_mean']}, "
            f"recall_attempt_mean="
            f"{row['triple_recall_attempt_mean']}, "
            f"f1_attempt_mean={row['triple_f1_attempt_mean']}, "
            f"f1_successful_mean={row['triple_f1_mean']}, "
            f"failure_rate={row['failure_rate']}, "
            f"exact_match_rate={row['exact_match_rate']}"
        )
