from contextlib import contextmanager
import json
from pathlib import Path
import sys
from time import perf_counter

from rdflib import Graph

from src.config import PHEROMONE_SPARQL_GENERATION_MINIMUM
from src.consistency import (
    InconsistentUpdateError,
    apply_and_repair,
    disjoint_pairs,
    local_name as _local_name,
)
from src.generate_sparQL import (
    _extract_sparql_update,
    retrieve_blurbs,
    strongest_communities,
)
from src.preprocessing import MAIN_ONTOLOGY

# Re-exported for callers/tests that imported these from helper historically.
__all__ = [
    "InconsistentUpdateError",
    "_execute_sparQL_command",
    "_disjointness_violations",
]


def _load_blackboard_items(blackboard_path):
    if not blackboard_path.exists():
        blackboard_path.parent.mkdir(parents=True, exist_ok=True)
        blackboard_path.touch()
        return {}

    items = {}
    with blackboard_path.open("r", encoding="utf8") as blackboard:
        for line in blackboard:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            items[item["community_id"]] = item
    return items


def _write_blackboard_items(blackboard_path, items):
    blackboard_path.parent.mkdir(parents=True, exist_ok=True)
    with blackboard_path.open("w", encoding="utf8") as blackboard:
        for item in items.values():
            blackboard.write(json.dumps(item) + "\n")

def _disjointness_violations(graph: Graph) -> set[tuple]:
    """Back-compat wrapper: classes pulled into two disjoint categories via subClassOf.

    Superseded by src.consistency (which also catches domain/range-inferred
    clashes and repairs instead of only detecting). Kept for callers/tests that
    imported this name. Returns (class, cat_a, cat_b) tuples.
    """
    from src.consistency import categories, class_categories

    cats = categories(graph)
    pairs = disjoint_pairs(graph)
    violations: set[tuple] = set()
    for cls in set(graph.subjects()):
        member = class_categories(graph, cls, cats)
        for pair in pairs:
            a, b = tuple(pair)
            if a in member and b in member:
                low, high = sorted((a, b), key=str)
                violations.add((cls, low, high))
    return violations


def _execute_sparQL_command(
    ttl_path,
    command,
    output_path="_raw_outputs/modified_simplified_xr.ttl",
    *,
    repair=True,
    autodeclare=True,
):
    base = Graph()
    base.parse(ttl_path, format="ttl")
    command = _extract_sparql_update(command)

    graph, report = apply_and_repair(
        base, command, repair=repair, autodeclare=autodeclare
    )
    print(report)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=output_path, format="ttl")
    return output_path, report

def _generate_sparQL():
    user_input = input("Generate hypothesis and proposed relations? (y/n): ")
    user_input = user_input.strip().lower()

    if user_input == "y":
        communities = strongest_communities(minimum=PHEROMONE_SPARQL_GENERATION_MINIMUM, k=3)
        sparql_command = retrieve_blurbs(communities=communities)
        try:
            _, report = _execute_sparQL_command(
                ttl_path=str(MAIN_ONTOLOGY), # run the sparQL command on the original ontology we preprocessed
                command=sparql_command,
            )
        except InconsistentUpdateError as error:
            print(f"SPARQL update rejected (ontology left unchanged):\n {error}")
            print(f"Offending SPARQL:\n {sparql_command}")
            return

        print(f"SPARQL commands:\n {sparql_command}")
        if not report.clean:
            print(
                "Note: the update was repaired before writing "
                f"({len(report.dropped)} dropped, {len(report.redundant)} collapsed, "
                f"{len(report.autodeclared)} predicate(s) auto-declared)."
            )

    elif user_input == "n":
        raise SystemExit(0)
    else:
        raise RuntimeError("Please enter 'y' or 'n'.")
    
@contextmanager
def timed_stage(name: str):
    start = perf_counter()
    try:
        yield
    finally:
        elapsed = perf_counter() - start
        print(f"{name} finished in {elapsed:.2f}s")

if __name__ == "__main__":
    _execute_sparQL_command(
        ttl_path="_raw_inputs/simplified_xr.ttl",
        command="""
            PREFIX ex: <http://example.org/3dui-ontology#>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

            INSERT DATA {
            ex:HumanUXIssues a owl:Class ;
                rdfs:label "Human UX Issues" ;
                rdfs:comment "Human UX issues caused by visual-vestibular mismatch." ;
                rdfs:subClassOf ex:HumanFactor .

            ex:CybersicknessOrDisorientation a owl:Class ;
                rdfs:label "Cybersickness or Disorientation" ;
                rdfs:comment "Cybersickness or disorientation resulting from viewpoint movement." ;
                rdfs:subClassOf ex:HumanFactor .

            <http://example.org/3dui-ontology#TravelTechnique> ex:causes ex:HumanUXIssues .
            <http://example.org/3dui-ontology#TravelTechnique> ex:causes ex:CybersicknessOrDisorientation .
            }
        """
    )
