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
        benchmark_csv_path: str = "benchmark_results2.csv",
        output_csv_path: str = "analysis/ttl_diff_results.csv",
    ):
        output_fields = [
            "run_id",
            "community_pruned",
            "model",
            "experiment_type",
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
                    "error": "",
                }

                try:
                    metrics = self.ttlDiff(
                        row["detached_ground_truth_ttl_path"],
                        row["output_ttl_path"],
                        row["modified_original_ttl_path"],
                    )
                    result_row.update(metrics)
                except Exception as exc:
                    result_row["error"] = str(exc)

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
        grouped_rows = {}

        with open(diff_results_csv_path, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                if row.get("error"):
                    continue

                experiment_type = row.get("experiment_type", "")
                if not experiment_type:
                    continue

                grouped_rows.setdefault(experiment_type, []).append(row)

        summary_rows = []
        for experiment_type, rows in sorted(grouped_rows.items()):
            summary_row = {
                "experiment_type": experiment_type,
                "num_trials": len(rows),
                "exact_match_count": sum(
                    row.get("exact_graph_match") == "True" for row in rows
                ),
                "exact_match_rate": (
                    sum(row.get("exact_graph_match") == "True" for row in rows)
                    / len(rows)
                    if rows
                    else 0
                ),
            }

            for column in score_columns:
                values = [float(row[column]) for row in rows if row.get(column) != ""]
                summary_row[f"{column}_mean"] = mean(values) if values else 0
                summary_row[f"{column}_median"] = median(values) if values else 0
                summary_row[f"{column}_stdev"] = stdev(values) if len(values) > 1 else 0
                summary_row[f"{column}_min"] = min(values) if values else 0
                summary_row[f"{column}_max"] = max(values) if values else 0

            summary_rows.append(summary_row)

        if output_csv_path:
            output_fields = [
                "experiment_type",
                "num_trials",
                "exact_match_count",
                "exact_match_rate",
            ]
            for column in score_columns:
                output_fields.extend(
                    [
                        f"{column}_mean",
                        f"{column}_median",
                        f"{column}_stdev",
                        f"{column}_min",
                        f"{column}_max",
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
            f"precision_mean={row['triple_precision_mean']}, "
            f"recall_mean={row['triple_recall_mean']}, "
            f"f1_mean={row['triple_f1_mean']}, "
            f"exact_match_rate={row['exact_match_rate']}"
        )

