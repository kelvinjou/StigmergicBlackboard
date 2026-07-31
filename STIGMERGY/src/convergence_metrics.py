"""Cluster-level convergence metrics for the stigmergy-vs-baseline benchmark.

Purpose:
    ``delta_comparisons.py`` diffs two arms edge-by-edge. This module instead
    scores a SINGLE arm against the concept-clustered gold set
    (``_benchmarks/clustered_gold.csv``) to answer the question the original
    schema.org benchmark could not: when several paraphrases describe the same
    underlying fact, does the arm CONVERGE onto one shared relationship edge, or
    does it mint a fresh predicate per paraphrase?

Inputs (per arm):
    Each arm writes to ``_raw_outputs/<RUN_TAG>/`` a
    ``modified_schema_org.provenance.jsonl`` sidecar. Every line is one triple
    added by an accepted SPARQL update, tagged with the ``evidence_row`` that
    produced it. We treat that sidecar as the universe of added edges (it already
    excludes base-ontology triples), map each evidence_row to its gold cluster,
    and compute per-cluster + per-arm metrics.

Metrics (per cluster, aggregated per arm):
    - predicate_convergence_ratio: distinct minted relationship predicates in a
      cluster / evidence rows in that cluster that produced any edge.
      1/N (== 1/rows_with_edges reaching the floor of one shared predicate) is
      perfect convergence; -> 1.0 means a new predicate per paraphrase.
    - gold recall: cluster counts as recalled if >=1 added content edge matches
      the cluster's single gold edge (subject/object by local name, predicate by
      kind stem so URI drift is tolerated).
    - gold precision: matching content edges / all content edges in the cluster.
    - redundant_edge_rate: content edges beyond one-per-(subject,object) pair.
    - hallucination: content edges attributed to a no-edge (negative-control)
      cluster, and content edges that match no gold subject/object at all.

Usage:
    python -m src.convergence_metrics                 # all arms under _raw_outputs
    python -m src.convergence_metrics --arms a0_hnsw_only a3_stig_persist
    python -m src.convergence_metrics --gold _benchmarks/clustered_gold.csv
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from csv import DictReader
import json
from pathlib import Path

# Predicates that describe ontology structure rather than an asserted
# relationship between two concepts. A "content edge" is any added triple whose
# predicate is NOT one of these; its predicate URI is the minted relationship
# property whose reinvention we are measuring.
STRUCTURAL_PREDICATES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://www.w3.org/2000/01/rdf-schema#subClassOf",
    "http://www.w3.org/2000/01/rdf-schema#subPropertyOf",
    "http://www.w3.org/2000/01/rdf-schema#domain",
    "http://www.w3.org/2000/01/rdf-schema#range",
    "https://schema.org/domainIncludes",
    "https://schema.org/rangeIncludes",
}

# Predicate-kind stems used for lenient gold matching. The gold file names a
# predicate_kind (causes/supports/requires/contradicts/...) and we match a
# minted predicate URI if its local name contains that stem, so
# causesHypertension and causesHighSodiumDiet both satisfy the "causes" gold.
DEFAULT_OUTPUTS_ROOT = Path("_raw_outputs")
DEFAULT_GOLD = Path("_benchmarks/clustered_gold.csv")
PROVENANCE_NAME = "modified_schema_org.provenance.jsonl"


def local_name(uri: str) -> str:
    """Trailing path/fragment segment of a URI, lower-cased for comparison."""
    if uri is None:
        return ""
    tail = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return tail.lower()


def load_gold(path: Path) -> tuple[dict, dict]:
    """Return (clusters_by_id, cluster_by_evidence_row)."""
    clusters: dict[str, dict] = {}
    row_to_cluster: dict[int, str] = {}
    with path.open("r", encoding="utf8") as gold_file:
        for record in DictReader(gold_file):
            cluster_id = record["cluster_id"].strip()
            rows = [
                int(part)
                for part in record["evidence_rows"].split(",")
                if part.strip()
            ]
            clusters[cluster_id] = {
                "cluster_id": cluster_id,
                "concept": record.get("concept", ""),
                "evidence_rows": rows,
                "gold_subject": record.get("gold_subject", "").strip(),
                "gold_predicate": record.get("gold_predicate", "").strip(),
                "gold_object": record.get("gold_object", "").strip(),
                "predicate_kind": record.get("predicate_kind", "").strip().lower(),
                "expect_edge": record.get("expect_edge", "").strip().lower() == "yes",
            }
            for row in rows:
                row_to_cluster[row] = cluster_id
    return clusters, row_to_cluster


def load_content_edges(provenance_path: Path) -> list[dict]:
    """One entry per added content edge: {evidence_row, subject, predicate, object}.

    De-duplicates identical (row, triple) lines that provenance may emit more
    than once, so counts reflect distinct asserted edges.
    """
    seen: set[tuple] = set()
    edges: list[dict] = []
    with provenance_path.open("r", encoding="utf8") as sidecar:
        for line in sidecar:
            if not line.strip():
                continue
            record = json.loads(line)
            predicate_uri = record["predicate"]["value"]
            if predicate_uri in STRUCTURAL_PREDICATES:
                continue
            row = record.get("evidence_row")
            key = (
                row,
                record["subject"]["value"],
                predicate_uri,
                record["object"]["value"],
            )
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "evidence_row": row,
                    "subject": record["subject"]["value"],
                    "predicate": predicate_uri,
                    "object": record["object"]["value"],
                }
            )
    return edges


def matches_gold(edge: dict, cluster: dict) -> bool:
    """Lenient gold match: subject/object by local name, predicate by kind stem."""
    subject_ok = local_name(edge["subject"]) == local_name(cluster["gold_subject"])
    object_ok = local_name(edge["object"]) == local_name(cluster["gold_object"])
    kind = cluster["predicate_kind"]
    predicate_ok = bool(kind) and kind in local_name(edge["predicate"])
    return subject_ok and object_ok and predicate_ok


def score_arm(clusters: dict, row_to_cluster: dict, edges: list[dict]) -> dict:
    """Per-cluster and arm-level convergence metrics for one arm's edges."""
    edges_by_cluster: dict[str, list[dict]] = defaultdict(list)
    unattributed = 0
    for edge in edges:
        cluster_id = row_to_cluster.get(edge["evidence_row"])
        if cluster_id is None:
            unattributed += 1
            continue
        edges_by_cluster[cluster_id].append(edge)

    per_cluster = {}
    for cluster_id, cluster in clusters.items():
        cluster_edges = edges_by_cluster.get(cluster_id, [])
        distinct_predicates = {edge["predicate"] for edge in cluster_edges}
        rows_with_edges = {edge["evidence_row"] for edge in cluster_edges}
        subject_object_pairs = {
            (local_name(edge["subject"]), local_name(edge["object"]))
            for edge in cluster_edges
        }
        matched = [edge for edge in cluster_edges if matches_gold(edge, cluster)]

        convergence = (
            len(distinct_predicates) / len(rows_with_edges)
            if rows_with_edges
            else None
        )
        redundant = max(0, len(cluster_edges) - len(subject_object_pairs))

        per_cluster[cluster_id] = {
            "concept": cluster["concept"],
            "expect_edge": cluster["expect_edge"],
            "n_evidence": len(cluster["evidence_rows"]),
            "rows_with_edges": len(rows_with_edges),
            "total_edges": len(cluster_edges),
            "distinct_predicates": len(distinct_predicates),
            "predicate_convergence_ratio": convergence,
            "gold_recall": bool(matched) if cluster["expect_edge"] else None,
            "gold_precision": (
                len(matched) / len(cluster_edges) if cluster_edges else None
            ),
            "redundant_edges": redundant,
            "hallucinated_edges": (
                len(cluster_edges) if not cluster["expect_edge"] else 0
            ),
        }

    positive_clusters = [
        metrics for metrics in per_cluster.values() if metrics["expect_edge"]
    ]
    recalled = sum(1 for m in positive_clusters if m["gold_recall"])
    convergence_values = [
        m["predicate_convergence_ratio"]
        for m in positive_clusters
        if m["predicate_convergence_ratio"] is not None
    ]
    total_edges = sum(m["total_edges"] for m in per_cluster.values())
    matched_edges = sum(
        m["gold_precision"] * m["total_edges"]
        for m in per_cluster.values()
        if m["gold_precision"] is not None
    )

    arm_summary = {
        "clusters_recalled": recalled,
        "positive_clusters": len(positive_clusters),
        "cluster_recall": recalled / len(positive_clusters) if positive_clusters else None,
        "mean_predicate_convergence": (
            sum(convergence_values) / len(convergence_values)
            if convergence_values
            else None
        ),
        "total_content_edges": total_edges,
        "overall_precision": matched_edges / total_edges if total_edges else None,
        "total_redundant_edges": sum(m["redundant_edges"] for m in per_cluster.values()),
        "total_hallucinated_edges": sum(m["hallucinated_edges"] for m in per_cluster.values()),
        "unattributed_edges": unattributed,
    }
    return {"per_cluster": per_cluster, "summary": arm_summary}


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def discover_arms(outputs_root: Path) -> list[str]:
    return sorted(
        directory.name
        for directory in outputs_root.iterdir()
        if directory.is_dir() and (directory / PROVENANCE_NAME).exists()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster-convergence metrics per experiment arm."
    )
    parser.add_argument("--outputs-root", type=Path, default=DEFAULT_OUTPUTS_ROOT)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument(
        "--arms",
        nargs="*",
        default=None,
        help="RUN_TAG dir names to score (default: every arm with a provenance sidecar).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clusters, row_to_cluster = load_gold(args.gold)
    arms = args.arms or discover_arms(args.outputs_root)
    if not arms:
        print(f"No arms with a {PROVENANCE_NAME} sidecar under {args.outputs_root}.")
        return

    summary_columns = [
        "cluster_recall",
        "mean_predicate_convergence",
        "overall_precision",
        "total_content_edges",
        "total_redundant_edges",
        "total_hallucinated_edges",
    ]

    print(f"Gold: {args.gold}  ({len(clusters)} clusters)\n")
    arm_rows = []
    for arm in arms:
        provenance_path = args.outputs_root / arm / PROVENANCE_NAME
        if not provenance_path.exists():
            print(f"[skip] {arm}: no {PROVENANCE_NAME}")
            continue
        result = score_arm(clusters, row_to_cluster, load_content_edges(provenance_path))
        arm_rows.append((arm, result["summary"]))

        print(f"=== arm: {arm} ===")
        header = (
            f"  {'cluster':<8}{'edges':>6}{'preds':>6}"
            f"{'conv':>7}{'recall':>8}{'prec':>7}{'redund':>7}{'halluc':>7}"
        )
        print(header)
        for cluster_id, metrics in result["per_cluster"].items():
            print(
                f"  {cluster_id:<8}"
                f"{metrics['total_edges']:>6}"
                f"{metrics['distinct_predicates']:>6}"
                f"{_fmt(metrics['predicate_convergence_ratio']):>7}"
                f"{_fmt(metrics['gold_recall']):>8}"
                f"{_fmt(metrics['gold_precision']):>7}"
                f"{metrics['redundant_edges']:>7}"
                f"{metrics['hallucinated_edges']:>7}"
            )
        print()

    if arm_rows:
        print("=== arm summary ===")
        name_width = max(len(arm) for arm, _ in arm_rows) + 2
        print("  " + f"{'arm':<{name_width}}" + "".join(f"{col:>26}" for col in summary_columns))
        for arm, summary in arm_rows:
            print(
                "  "
                + f"{arm:<{name_width}}"
                + "".join(f"{_fmt(summary[col]):>26}" for col in summary_columns)
            )


if __name__ == "__main__":
    main()
