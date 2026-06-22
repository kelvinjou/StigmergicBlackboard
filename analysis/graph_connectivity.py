import argparse
import csv
from pathlib import Path
from typing import Optional

from rdflib import BNode, Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD


Resource = (URIRef, BNode)


class GraphConnectivityAnalysis:
    """Measure how well a reconstructed community reconnects to the base graph."""

    STANDARD_VOCABULARY_NAMESPACES = (
        str(RDF),
        str(RDFS),
        str(OWL),
        str(XSD),
    )

    @staticmethod
    def _load_graph(path: str) -> Graph:
        graph = Graph()
        graph.parse(path, format="ttl")
        return graph

    @staticmethod
    def _resource_nodes(triples):
        nodes = set()
        for subject, _, obj in triples:
            if isinstance(subject, Resource):
                nodes.add(subject)
            if isinstance(obj, Resource):
                nodes.add(obj)
        return nodes

    @staticmethod
    def _is_standard_vocabulary_node(node):
        return isinstance(node, URIRef) and str(node).startswith(
            GraphConnectivityAnalysis.STANDARD_VOCABULARY_NAMESPACES
        )

    @staticmethod
    def _connector_direction(triple, community_nodes, retained_nodes):
        subject, _, obj = triple
        if (
            subject in community_nodes
            and obj in retained_nodes
            and not GraphConnectivityAnalysis._is_standard_vocabulary_node(obj)
        ):
            return "community_to_global"
        if (
            subject in retained_nodes
            and obj in community_nodes
            and not GraphConnectivityAnalysis._is_standard_vocabulary_node(
                subject
            )
        ):
            return "global_to_community"
        return None

    @staticmethod
    def _term_text(term, graph):
        return term.n3(graph.namespace_manager)

    def analyze_connectivity(
        self,
        original_path: str,
        modified_original_path: str,
        reinserted_path: str,
    ):
        original = self._load_graph(original_path)
        base = self._load_graph(modified_original_path)
        reinserted = self._load_graph(reinserted_path)

        original_triples = set(original)
        base_triples = set(base)
        reinserted_triples = set(reinserted)

        original_nodes = self._resource_nodes(original_triples)
        retained_nodes = self._resource_nodes(base_triples)

        # Pruning removes every incoming and outgoing triple for each community
        # class. Consequently, those resources disappear entirely from the base.
        community_nodes = original_nodes - retained_nodes

        expected_connectors = {
            triple
            for triple in original_triples
            if self._connector_direction(
                triple, community_nodes, retained_nodes
            )
        }

        recovered_connectors = expected_connectors & reinserted_triples
        missed_connectors = expected_connectors - reinserted_triples

        inserted_triples = reinserted_triples - base_triples
        inserted_nodes = self._resource_nodes(inserted_triples) - retained_nodes
        actual_connectors = {
            triple
            for triple in inserted_triples
            if self._connector_direction(triple, inserted_nodes, retained_nodes)
        }
        extra_connectors = actual_connectors - expected_connectors

        precision = (
            len(recovered_connectors) / len(actual_connectors)
            if actual_connectors
            else 0
        )
        recall = (
            len(recovered_connectors) / len(expected_connectors)
            if expected_connectors
            else 0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0
        )

        missing_base_triples = base_triples - reinserted_triples

        metrics = {
            "original_triples": len(original_triples),
            "base_triples": len(base_triples),
            "final_triples": len(reinserted_triples),
            "community_nodes": len(community_nodes),
            "expected_connectors": len(expected_connectors),
            "recovered_connectors": len(recovered_connectors),
            "missed_connectors": len(missed_connectors),
            "extra_connectors": len(extra_connectors),
            "connector_precision": precision,
            "connector_recall": recall,
            "connector_f1": f1,
            "missing_base_triples": len(missing_base_triples),
            "base_preserved": not missing_base_triples,
            "exact_global_match": original_triples == reinserted_triples,
        }

        details = []
        detail_groups = (
            ("recovered", recovered_connectors),
            ("missed", missed_connectors),
            ("extra", extra_connectors),
        )
        for status, triples in detail_groups:
            boundary_nodes = (
                community_nodes if status != "extra" else inserted_nodes
            )
            for subject, predicate, obj in sorted(
                triples, key=lambda triple: tuple(map(str, triple))
            ):
                details.append(
                    {
                        "status": status,
                        "direction": self._connector_direction(
                            (subject, predicate, obj),
                            boundary_nodes,
                            retained_nodes,
                        ),
                        "subject": self._term_text(subject, original),
                        "predicate": self._term_text(predicate, original),
                        "object": self._term_text(obj, original),
                    }
                )

        return metrics, details

    def run_benchmark_connectivity(
        self,
        benchmark_csv_path: str = "benchmark_results.csv",
        output_csv_path: str = "analysis/graph_connectivity_results.csv",
        details_csv_path: Optional[str] = (
            "analysis/graph_connectivity_details.csv"
        ),
    ):
        output_fields = [
            "run_id",
            "community_pruned",
            "model",
            "experiment_type",
            "original_triples",
            "base_triples",
            "final_triples",
            "community_nodes",
            "expected_connectors",
            "recovered_connectors",
            "missed_connectors",
            "extra_connectors",
            "connector_precision",
            "connector_recall",
            "connector_f1",
            "missing_base_triples",
            "base_preserved",
            "exact_global_match",
            "error",
        ]
        detail_fields = [
            "run_id",
            "community_pruned",
            "experiment_type",
            "status",
            "direction",
            "subject",
            "predicate",
            "object",
        ]

        output_rows = []
        detail_rows = []
        with open(benchmark_csv_path, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                result_row = {
                    "run_id": row.get("run_id", ""),
                    "community_pruned": row.get("community_pruned", ""),
                    "model": row.get("model", ""),
                    "experiment_type": row.get("experiment_type", ""),
                    "error": (row.get("error") or "").strip(),
                }

                if not result_row["error"]:
                    try:
                        metrics, details = self.analyze_connectivity(
                            row["input_ttl_path"],
                            row["modified_original_ttl_path"],
                            row["output_ttl_path"],
                        )
                        result_row.update(metrics)
                        for detail in details:
                            detail_rows.append(
                                {
                                    "run_id": result_row["run_id"],
                                    "community_pruned": result_row[
                                        "community_pruned"
                                    ],
                                    "experiment_type": result_row[
                                        "experiment_type"
                                    ],
                                    **detail,
                                }
                            )
                    except Exception as exc:
                        result_row["error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )

                output_rows.append(result_row)

        Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv_path, "w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=output_fields)
            writer.writeheader()
            writer.writerows(output_rows)

        if details_csv_path:
            Path(details_csv_path).parent.mkdir(
                parents=True, exist_ok=True
            )
            with open(details_csv_path, "w", newline="") as csv_file:
                writer = csv.DictWriter(
                    csv_file, fieldnames=detail_fields
                )
                writer.writeheader()
                writer.writerows(detail_rows)

        return output_rows, detail_rows

    def summarize_by_experiment(
        self,
        connectivity_results_csv_path: str = (
            "analysis/graph_connectivity_results.csv"
        ),
        output_csv_path: Optional[str] = (
            "analysis/graph_connectivity_score_summary.csv"
        ),
    ):
        grouped_rows = {}
        with open(connectivity_results_csv_path, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                if row.get("error"):
                    continue

                experiment_type = row.get("experiment_type", "")
                if not experiment_type:
                    continue

                grouped_rows.setdefault(experiment_type, []).append(row)

        summary_rows = []
        for experiment_type, rows in sorted(grouped_rows.items()):
            expected = sum(int(row["expected_connectors"]) for row in rows)
            recovered = sum(int(row["recovered_connectors"]) for row in rows)
            missed = sum(int(row["missed_connectors"]) for row in rows)
            extra = sum(int(row["extra_connectors"]) for row in rows)
            predicted = recovered + extra

            precision = recovered / predicted if predicted else 0
            recall = recovered / expected if expected else 0
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision + recall
                else 0
            )

            summary_rows.append(
                {
                    "experiment_type": experiment_type,
                    "num_trials": len(rows),
                    "expected_connectors": expected,
                    "predicted_connectors": predicted,
                    "recovered_connectors": recovered,
                    "missed_connectors": missed,
                    "extra_connectors": extra,
                    "connector_precision": precision,
                    "connector_recall": recall,
                    "connector_f1": f1,
                }
            )

        if output_csv_path:
            output_fields = [
                "experiment_type",
                "num_trials",
                "expected_connectors",
                "predicted_connectors",
                "recovered_connectors",
                "missed_connectors",
                "extra_connectors",
                "connector_precision",
                "connector_recall",
                "connector_f1",
            ]
            Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_csv_path, "w", newline="") as csv_file:
                writer = csv.DictWriter(
                    csv_file, fieldnames=output_fields
                )
                writer.writeheader()
                writer.writerows(summary_rows)

        return summary_rows


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze whether reconstructed communities restore their "
            "connections to the original global ontology."
        )
    )
    parser.add_argument(
        "--benchmark-csv", default="benchmark_results.csv"
    )
    parser.add_argument(
        "--output-csv",
        default="analysis/graph_connectivity_results.csv",
    )
    parser.add_argument(
        "--details-csv",
        default="analysis/graph_connectivity_details.csv",
    )
    parser.add_argument(
        "--summary-csv",
        default="analysis/graph_connectivity_score_summary.csv",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    analysis = GraphConnectivityAnalysis()
    rows, _ = analysis.run_benchmark_connectivity(
        benchmark_csv_path=args.benchmark_csv,
        output_csv_path=args.output_csv,
        details_csv_path=args.details_csv,
    )
    for row in rows:
        print(
            f"{row['community_pruned']} ({row['experiment_type']}): "
            f"connectors={row.get('recovered_connectors', '')}/"
            f"{row.get('expected_connectors', '')}, "
            f"precision={row.get('connector_precision', '')}, "
            f"recall={row.get('connector_recall', '')}, "
            f"f1={row.get('connector_f1', '')}, "
            f"base_preserved={row.get('base_preserved', '')}, "
            f"error={row.get('error', '')}"
        )

    print()
    summary_rows = analysis.summarize_by_experiment(
        connectivity_results_csv_path=args.output_csv,
        output_csv_path=args.summary_csv,
    )
    for row in summary_rows:
        print(
            f"{row['experiment_type']} overall: "
            f"precision={row['connector_precision']}, "
            f"recall={row['connector_recall']}, "
            f"f1={row['connector_f1']}, "
            f"recovered={row['recovered_connectors']}/"
            f"{row['expected_connectors']}, "
            f"extra={row['extra_connectors']}"
        )
