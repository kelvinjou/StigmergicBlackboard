"""Record evidence-to-edge provenance for generated ontology updates.

Purpose:
    The Turtle output contains the final RDF graph, but RDF triples alone do not
    retain which evidence row or blackboard claims caused an edge to be added.
    This module writes a JSON Lines sidecar next to the generated ontology. Each
    line represents one newly added triple and includes the evidence row, the
    selected source claims, community metadata, and the accepted SPARQL update.

Output:
    ``modified_schema_org.ttl`` produces
    ``modified_schema_org.provenance.jsonl``.

The sidecar is intentionally separate from the ontology so comparison tooling
can group w_phero and no_phero results by evidence row without introducing
provenance vocabulary into the generated schema itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from rdflib.term import Node


def provenance_path_for(output_path: str | Path) -> Path:
    """Return the JSONL sidecar path associated with an ontology output."""
    output_path = Path(output_path)
    return output_path.with_name(f"{output_path.stem}.provenance.jsonl")


def _term_record(term: Node) -> dict[str, str]:
    """Preserve both a readable value and RDF-aware N3 representation."""
    return {
        "value": str(term),
        "n3": term.n3(),
        "type": type(term).__name__,
    }


def _claim_records(communities: Iterable[dict]) -> list[dict]:
    """Flatten the selected communities into traceable source-claim records."""
    claims = []
    for community in communities:
        for index, blurb in enumerate(community.get("blurb", []), start=1):
            claims.append(
                {
                    "claim_id": f"{community['community_id']}:{index}",
                    "community_id": community["community_id"],
                    "community": community.get("community"),
                    "evidence": blurb.get("evidence"),
                    "claim": blurb.get("text"),
                    "heuristic": blurb.get("heuristic"),
                    "deposit": blurb.get("deposit"),
                }
            )
    return claims


def write_update_provenance(
    *,
    output_path: str | Path,
    blackboard_path: str | Path,
    evidence_row: str,
    communities: Iterable[dict],
    command: str,
    added_triples: Iterable[tuple[Node, Node, Node]],
    reset: bool = False,
) -> Path:
    """Write one provenance line for every triple added by an accepted update.

    ``reset`` should be true when the ontology output is being created from the
    base ontology. This keeps a stale sidecar from a previous run from becoming
    associated with a newly generated graph.
    """
    sidecar_path = provenance_path_for(output_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    claims = _claim_records(communities)
    evidence = list(
        dict.fromkeys(
            claim["evidence"]
            for claim in claims
            if claim.get("evidence") is not None
        )
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    mode = "w" if reset else "a"

    with sidecar_path.open(mode, encoding="utf8") as sidecar:
        for subject, predicate, object_ in sorted(added_triples, key=lambda triple: tuple(map(str, triple))):
            record = {
                "schema_version": 1,
                "recorded_at": timestamp,
                "evidence_row": int(evidence_row) if evidence_row.isdigit() else evidence_row,
                "blackboard_path": str(blackboard_path),
                "evidence": evidence,
                "source_claims": claims,
                "subject": _term_record(subject),
                "predicate": _term_record(predicate),
                "object": _term_record(object_),
                "sparql_command": command,
            }
            sidecar.write(json.dumps(record, ensure_ascii=True) + "\n")

    return sidecar_path
