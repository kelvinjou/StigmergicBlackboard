import json
from pathlib import Path
import sys

from rdflib import Graph

from src.generate_sparQL import (
    _extract_sparql_update,
    retrieve_blurbs,
    strongest_communities,
)


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

def _execute_sparQL_command(
    ttl_path,
    command,
    output_path="_raw_outputs/modified_simplified_xr.ttl",
):
    g = Graph()
    g.parse(ttl_path, format="ttl")
    command = _extract_sparql_update(command)
    g.update(command)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=output_path, format="ttl")
    return output_path

def _generate_sparQL():
    user_input = input("Generate hypothesis and proposed relations? (y/n): ")
    user_input = user_input.strip().lower()

    if user_input == "y":
        communities = strongest_communities(minimum=2, k=3)
        sparql_command = retrieve_blurbs(communities=communities)
        _execute_sparQL_command(
            ttl_path="_raw_inputs/simplified_xr.ttl",
            command=sparql_command
        )

    elif user_input == "n":
        raise SystemExit(0)
    else:
        raise RuntimeError("Please enter 'y' or 'n'.")

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
