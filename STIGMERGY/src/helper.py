from contextlib import contextmanager
import json
from pathlib import Path
import sys
from time import perf_counter

from rdflib import Graph
from rdflib.namespace import OWL, RDFS

from src.config import NEW_EVIDENCE_PERSISTENCE, PHEROMONE_SPARQL_GENERATION_MINIMUM
from src.generate_sparQL import (
    _extract_sparql_update,
    retrieve_blurbs,
    strongest_communities,
)
from src.preprocessing import MAIN_ONTOLOGY


class InconsistentUpdateError(RuntimeError):
    """A SPARQL update would place a class under two owl:disjointWith branches."""


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

def _local_name(uri) -> str:
    text = str(uri)
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text


def _disjointness_violations(graph: Graph) -> set[tuple]:
    """Classes that are transitively rdfs:subClassOf two owl:disjointWith branches.

    This is the exact inconsistency Option 2 introduced (a device made a subclass
    of both HardwareComponent and the disjoint InteractionTechnique). It is a
    pure traversal of the already-parsed graph -- no OWL reasoner and no LLM
    call -- so it adds no network latency. Returns (class, branch_a, branch_b)
    with the branch pair order-normalized so mirror declarations collapse.
    """
    violations: set[tuple] = set()
    for branch_a, _, branch_b in graph.triples((None, OWL.disjointWith, None)):
        subs_a = set(graph.transitive_subjects(RDFS.subClassOf, branch_a))
        subs_b = set(graph.transitive_subjects(RDFS.subClassOf, branch_b))
        low, high = sorted((branch_a, branch_b), key=str)
        for clash in subs_a & subs_b:
            violations.add((clash, low, high))
    return violations


def _execute_sparQL_command(
    ttl_path,
    command,
    output_path="_raw_outputs/modified_simplified_xr.ttl",
):
    g = Graph()
    output_path = Path(output_path)

    if NEW_EVIDENCE_PERSISTENCE and output_path.exists():
        g.parse(output_path, format="ttl")
        # update community embedding and also HNSW 

    else:
        g.parse(ttl_path, format="ttl")
    # Snapshot pre-existing violations so the guard only rejects NEW ones the
    # update introduces, never inconsistencies already baked into the ontology.
    before = _disjointness_violations(g)
    command = _extract_sparql_update(command)
    g.update(command)

    introduced = _disjointness_violations(g) - before
    if introduced:
        detail = "; ".join(
            f"{_local_name(c)} would be subClassOf both "
            f"{_local_name(a)} and {_local_name(b)} (disjoint)"
            for c, a, b in sorted(introduced, key=str)
        )
        raise InconsistentUpdateError(
            f"Rejected SPARQL update; not written to {output_path}. "
            f"It introduces disjointness violations: {detail}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)


    g.serialize(destination=output_path, format="ttl")
    return output_path

def _generate_sparQL():
    user_input = input("Generate hypothesis and proposed relations? (y/n): ")
    user_input = user_input.strip().lower()

    if user_input == "y":
        communities = strongest_communities(minimum=PHEROMONE_SPARQL_GENERATION_MINIMUM, k=3)
        sparql_command = retrieve_blurbs(communities=communities)
        try:
            _execute_sparQL_command(
                ttl_path=str(MAIN_ONTOLOGY), # run the sparQL command on the original ontology we preprocessed
                command=sparql_command
            )
        except InconsistentUpdateError as error:
            print(f"SPARQL update rejected (ontology left unchanged):\n {error}")
            print(f"Offending SPARQL:\n {sparql_command}")
            return

        print(f"SPARQL commands:\n {sparql_command}")

    elif user_input == "n":
        raise SystemExit(0)
    else:
        raise RuntimeError("Please enter 'y' or 'n'.")
    
def _new_evidence_ontology_persistence():
    # each run should use its own summary.txt, enhanced_xr.ttl
    # for each run, create a copy of the embedding if it doesn't exist yet
    # add the new embedding to pkl, add the new HNSW

    pass
    
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
