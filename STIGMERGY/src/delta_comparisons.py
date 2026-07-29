"""Compare ontology delta edges side by side, grouped by evidence row.

Purpose:
    Compare the final w_phero and no_phero RDF graphs while using their
    provenance sidecars to map each run-only edge back to the evidence row and
    source claims that produced it.

Output ordering:
    The CSV has one row per evidence row in numeric ascending order. The
    w_phero and no_phero results are adjacent columns in that row, so evidence
    1 is compared with evidence 1 before moving to evidence 2. Edges and claims
    within each cell are sorted as well, making repeated runs deterministic.

Default output:
    _raw_outputs/schema_org_delta_edges_by_evidence.csv
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from csv import DictWriter
import json
from pathlib import Path

from rdflib import Graph, RDF, RDFS


DEFAULT_W_DIR = Path("_raw_outputs/schema_org_w_phero")
DEFAULT_NO_DIR = Path("_raw_outputs/schema_org_no_phero")
DEFAULT_OUTPUT = Path("_raw_outputs/schema_org_delta_edges_by_evidence.csv")

IGNORE_PREDICATES = {
    RDF.type,
    RDFS.label,
    RDFS.comment,
}

RUN_ORDER = ("w_phero", "no_phero")


def load_graph(path: Path) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle")
    return graph


def triple_key(triple) -> tuple[str, str, str]:
    """Use N3 forms so URI, blank-node, literal, language, and datatype match."""
    return tuple(term.n3() for term in triple)


def provenance_triple_key(record: dict) -> tuple[str, str, str]:
    return (
        record["subject"]["n3"],
        record["predicate"]["n3"],
        record["object"]["n3"],
    )


def load_provenance(path: Path) -> dict[tuple[str, str, str], list[dict]]:
    records_by_triple = defaultdict(list)
    with path.open("r", encoding="utf8") as provenance:
        for line_number, line in enumerate(provenance, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                records_by_triple[provenance_triple_key(record)].append(record)
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(
                    f"Invalid provenance record at {path}:{line_number}"
                ) from error
    return records_by_triple


def is_edge(triple) -> bool:
    _, predicate, _ = triple
    return predicate not in IGNORE_PREDICATES


def evidence_sort_key(value) -> tuple[int, int | str]:
    """Sort numeric evidence naturally and place unknown values at the end."""
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def claim_sort_key(claim: dict) -> tuple[str, str, str]:
    return (
        str(claim.get("community_id", "")),
        str(claim.get("claim_id", "")),
        str(claim.get("claim", "")),
    )


def collect_run_delta(
    *,
    run: str,
    delta: Graph,
    provenance_by_triple: dict[tuple[str, str, str], list[dict]],
    grouped: dict,
) -> int:
    """Attach each graph-level delta edge to its originating evidence row."""
    edge_count = 0
    for triple in sorted(delta, key=triple_key):
        if not is_edge(triple):
            continue

        edge_count += 1
        key = triple_key(triple)
        provenance_records = provenance_by_triple.get(key)

        # Keep unattributed deltas visible instead of silently dropping them.
        if not provenance_records:
            grouped["unknown"][run]["edges"].add(key)
            continue

        for record in provenance_records:
            evidence_row = record.get("evidence_row", "unknown")
            bucket = grouped[evidence_row][run]
            bucket["edges"].add(key)
            bucket["evidence"].update(record.get("evidence", []))
            for claim in record.get("source_claims", []):
                claim_key = (
                    str(claim.get("claim_id", "")),
                    str(claim.get("claim", "")),
                )
                bucket["claims"][claim_key] = claim

    return edge_count


def format_edges(edges: set[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"{index}. {subject} | {predicate} | {object_}"
        for index, (subject, predicate, object_) in enumerate(sorted(edges), start=1)
    )


def format_claims(claims: dict[tuple[str, str], dict]) -> str:
    ordered_claims = sorted(claims.values(), key=claim_sort_key)
    return "\n".join(
        f"{index}. [{claim.get('community_id', 'unknown')}] "
        f"{claim.get('claim', '')}"
        for index, claim in enumerate(ordered_claims, start=1)
    )


def format_evidence(group: dict) -> str:
    evidence = {
        text
        for run in RUN_ORDER
        for text in group[run]["evidence"]
        if text
    }
    return "\n".join(sorted(evidence))


def compare_by_evidence(
    w_dir: Path,
    no_dir: Path,
    output_path: Path,
) -> tuple[int, int, int]:
    w_graph = load_graph(w_dir / "modified_schema_org.ttl")
    no_graph = load_graph(no_dir / "modified_schema_org.ttl")
    w_provenance = load_provenance(
        w_dir / "modified_schema_org.provenance.jsonl"
    )
    no_provenance = load_provenance(
        no_dir / "modified_schema_org.provenance.jsonl"
    )

    grouped = defaultdict(
        lambda: {
            run: {
                "edges": set(),
                "claims": {},
                "evidence": set(),
            }
            for run in RUN_ORDER
        }
    )

    w_edge_count = collect_run_delta(
        run="w_phero",
        delta=w_graph - no_graph,
        provenance_by_triple=w_provenance,
        grouped=grouped,
    )
    no_edge_count = collect_run_delta(
        run="no_phero",
        delta=no_graph - w_graph,
        provenance_by_triple=no_provenance,
        grouped=grouped,
    )

    rows = []
    for evidence_row in sorted(grouped, key=evidence_sort_key):
        group = grouped[evidence_row]
        rows.append(
            {
                "evidence_number": evidence_row,
                "evidence": format_evidence(group),
                "w_phero_delta_edge_count": len(group["w_phero"]["edges"]),
                "w_phero_delta_edges": format_edges(group["w_phero"]["edges"]),
                "w_phero_claims": format_claims(group["w_phero"]["claims"]),
                "no_phero_delta_edge_count": len(group["no_phero"]["edges"]),
                "no_phero_delta_edges": format_edges(group["no_phero"]["edges"]),
                "no_phero_claims": format_claims(group["no_phero"]["claims"]),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf8", newline="") as output:
        writer = DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), w_edge_count, no_edge_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare w_phero and no_phero delta edges by evidence row."
    )
    parser.add_argument("--w-dir", type=Path, default=DEFAULT_W_DIR)
    parser.add_argument("--no-dir", type=Path, default=DEFAULT_NO_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    row_count, w_edge_count, no_edge_count = compare_by_evidence(
        w_dir=args.w_dir,
        no_dir=args.no_dir,
        output_path=args.output,
    )
    print(f"Evidence rows: {row_count}")
    print(f"w_phero-only edges: {w_edge_count}")
    print(f"no_phero-only edges: {no_edge_count}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
