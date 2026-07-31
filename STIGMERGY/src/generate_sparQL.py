from __future__ import annotations

# get strength > x, then apply top k Need a better way later on
"""
1. filter jsonl strength > 2
2. apply top K
3. retrieve the blurb array. (need some prompt engineering to format all the array values properly)
4. 
"""

from pathlib import Path
import json
import heapq
import pickle
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import config
from src.helper import _extract_sparql_update
from llm.lmstudio_llm import LMStudioLLM

BLACKBOARD_DIR = PROJECT_ROOT / config.run_output_dir()
ONTOLOGY_EMBEDDING_CACHE_PATH = config.ONTOLOGY_EMBEDDING_CACHE_PATH
SPARQL_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "llm/prompts/sparQL_generation_sys_prompt.md"


def _blackboard_sort_key(path: Path) -> tuple[int, str]:
    match = re.fullmatch(r"bb(\d+)\.jsonl", path.name)
    if match:
        return int(match.group(1)), path.name
    return sys.maxsize, path.name


def _blackboard_paths(blackboard_path: str | Path | None) -> list[Path]:
    if blackboard_path is not None:
        return [Path(blackboard_path)]
    return sorted(BLACKBOARD_DIR.glob("bb*.jsonl"), key=_blackboard_sort_key)


def blackboard_paths(blackboard_path: str | Path | None = None) -> list[Path]:
    return _blackboard_paths(blackboard_path)


# apply minimum strength filtering then get top K
def strongest_communities(
    minimum: float,
    k: int,
    blackboard_path: str | Path | None = None,
) -> list[dict]:
    qualifiers = []
    for path in _blackboard_paths(blackboard_path):
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                record = json.loads(line)
                # Skip records that carry a pheromone trail (tau) but no blurb
                # for this evidence row. These appear only under
                # PHEROMONE_BLACKBOARD_PERSISTENCE: a community's tau is seeded
                # forward from prior evidence, but if the walk never actually
                # visited/blurbed it this evidence there is no claim text to feed
                # SPARQL generation. Selecting it would emit an empty-context
                # update. Arms without persistence are unaffected (every record
                # they write has a blurb).
                if not record.get("blurb"):
                    continue
                if record["strength"] >= minimum:
                    record["blackboard_path"] = str(path)
                    qualifiers.append(record)

    return heapq.nlargest(
        k,
        qualifiers,
        key=lambda record: record["strength"],
    )


def _object_properties_for_communities(
    ontology_cache: dict,
    communities: list[dict],
) -> dict:
    all_object_properties = ontology_cache.get("object_properties", {})
    selected_community_ids = {
        community["community_id"]
        for community in communities
    }

    connected_property_uris = {
        property_uri
        for community_id in selected_community_ids
        for property_uri in ontology_cache
        .get("items", {})
        .get(community_id, {})
        .get("connected_object_properties", [])
    }

    if not connected_property_uris:
        for property_uri, metadata in all_object_properties.items():
            domains = set(metadata.get("domains", []))
            ranges = set(metadata.get("ranges", []))
            if selected_community_ids & (domains | ranges):
                connected_property_uris.add(property_uri)

    return {
        property_uri: all_object_properties[property_uri]
        for property_uri in sorted(connected_property_uris)
        if property_uri in all_object_properties
    }
    
# a blank new LLM call per K community, and return SparQL command string
def retrieve_blurbs(communities: list[dict]) -> str:
    # a fancier way of "append every "text"" in list(community[blurb])"
    text_evidence = [
        blurb["text"]
        for community in communities
        for blurb in community["blurb"]
    ]
    community_context = [
        {
            "uri": community["community_id"],
            "description": community["community"],
            "strength": community["strength"],
            "blackboard_path": community.get("blackboard_path"),
        }
        for community in communities
    ]

    with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as file:
        ontology_cache = pickle.load(file)

    object_properties = _object_properties_for_communities(
        ontology_cache=ontology_cache,
        communities=communities,
    )

    agent = LMStudioLLM(
        system_prompt_path=SPARQL_SYSTEM_PROMPT_PATH,
        response_format=False,
        formatter=None,
    )

    response = agent.send_messages(
        json.dumps(
            {
                "ontology_config": {
                    "namespace_prefix": config.ONTOLOGY_NAMESPACE_PREFIX,
                    "namespace_uri": config.ONTOLOGY_NAMESPACE_URI,
                    "root_class_uri": config.ONTOLOGY_ROOT_CLASS_URI,
                    "relationship_property_type": config.RELATIONSHIP_PROPERTY_TYPE_QNAME,
                    "property_domain_predicate": config.PROPERTY_DOMAIN_PREDICATE_QNAME,
                    "property_range_predicate": config.PROPERTY_RANGE_PREDICATE_QNAME,
                    "sparql_prefixes": config.sparql_prefix_lines(),
                },
                "communities": community_context,
                # "object_properties": object_properties,
                "evidence": text_evidence,
            },
            ensure_ascii=True,
            indent=2,
        ),
        max_tokens=1500,
        temperature=0.0,
    )

    # print(f"RAW RESPONSE: {response}")

    return _format_sparql_response(response)


def _format_sparql_response(response: str) -> str:
    return f"```sparql\n{_extract_sparql_update(response)}\n```"
        


if __name__ == "__main__":
    communities = strongest_communities(minimum=2, k=3)
    print(retrieve_blurbs(communities=communities))
