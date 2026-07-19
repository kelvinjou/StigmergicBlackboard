"""
pick a new start to the node every time
do the stateless random walk. 

every node: cheap embedding similarity (modified TTL v. summary)
- comparing modified_original TTL community to summary.txt file
high scoring nodes: cached LLM sniff/proposal
"""
from __future__ import annotations

from pathlib import Path
import time
import pickle
import uuid
from openai import APIConnectionError, APIStatusError
from rdflib import Namespace

from llm.lmstudio_llm import LMStudioLLM
from src.helper import _load_blackboard_items, _write_blackboard_items
from src.preprocessing import (
    ONTOLOGY_EMBEDDING_CACHE_PATH,
    SUMMARY_EMBEDDING_CACHE_PATH,
    _ontology_embedding_similarity,
    _summary_embedding_similarity,
    get_embedding_model,
)
from src.walk_strategies import (
    RNG,
    _adjacent_walk,
    _direct_child_walk,
    _levy_jump,
    _starting_community,
)

BLACKBOARD = Path("_raw_outputs/blackboard.jsonl") # using jsonl b/c this file is continuously being updated. If using JSON, you must load the whole thing

EX = Namespace("http://example.org/3dui-ontology#")

def _decay_blackboard_strengths(decay=0.95):
    blackboard_items = _load_blackboard_items(BLACKBOARD)

    for item in blackboard_items.values():
        item["strength"] *= decay
    
    _write_blackboard_items(BLACKBOARD, blackboard_items)


def _append_blackboard_blurb(community_id, community, deposit_score, evidence, blurb):
    blackboard_items = _load_blackboard_items(BLACKBOARD)

    if community_id not in blackboard_items:
        blackboard_items[community_id] = {
            "id": str(uuid.uuid4()),
            "community_id": community_id,
            "community": community["semantic_description"],
        }

    # add reinforcement to visited community
    blackboard_items[community_id]["strength"] += deposit_score

    blackboard_items[community_id]["blurb"].append(
        {
            "evidence": evidence,
            "text": blurb,
            "strength": deposit_score,
        }
    )
    _write_blackboard_items(BLACKBOARD, blackboard_items)

def _generate_llm_relational_description(ontology, evidence):
    llm = LMStudioLLM() # swap with NVIDIANIMLLM if needed
    try:
        response = llm.send_messages(
            f"""
                Evidence 1: {ontology}
                Evidence 2: {evidence}

                Return only valid JSON matching the system schema.
            """
        )
        return response

    except (APIConnectionError, APIStatusError, ValueError) as error:
        print(f"Skipping LLM blurb: {error}")
        return None

def _compare_similarity_at_walk(
    current_community,
    evidence_text,
    evidence_embedding,
    path_confidence=1.0,
    semantic_weight=0.85,
):
    structure_weight = 1.0 - semantic_weight

    with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as ont_embed:
        ontology = pickle.load(ont_embed)

        community = ontology["items"][str(current_community)]
        semantic_embedding = community["semantic_embedding"]
        structure_embedding = community["structure_embedding"]

        semantic_score = get_embedding_model().similarity(evidence_embedding, semantic_embedding).item()
        structure_score = get_embedding_model().similarity(evidence_embedding, structure_embedding).item()
        final_score = (
            semantic_weight * semantic_score
            + structure_weight * structure_score
        )
        deposit_score = final_score * path_confidence
        print(
            f"semantic={semantic_score:.4f} "
            f"structure={structure_score:.4f} "
            f"final={deposit_score:.4f}\n"
            f"Semantic text: {community['semantic_description']}\n"
            f"Structure text: {community['structure_description']}\n"
            f"Summary text: {evidence_text}\n"
        )
        
        if final_score > 0.6:
            ontology = f"""
                Semantic text: {community['semantic_description']}
                Structure text: {community['structure_description']}
            """
            blurb = _generate_llm_relational_description(ontology=ontology, evidence=evidence_text)
            if blurb is None:
                print("Something went wrong? Perchance")
                return
                

            _append_blackboard_blurb(
                community_id=str(current_community),
                community=community,
                deposit_score=deposit_score,
                evidence=evidence_text,
                blurb=blurb,
            )


# Random-walk orchestration. 
# walk now owns the evidence loop
def walk(trial_count=5, steps_per_trial=10):
    walk_options = [
        ("top down", _direct_child_walk, 0.6),
        ("adjacent", _adjacent_walk, 0.3),
        ("levy jump", _levy_jump, 0.1),
    ]


    with (
        SUMMARY_EMBEDDING_CACHE_PATH.open("rb") as sum_embed
    ):
        summaries = pickle.load(sum_embed)
        for evidence_text, evidence_embedding in zip(
            summaries["descriptions"],
            summaries["embeddings"]
        ):
            for trial in range(1, trial_count + 1):
                _decay_blackboard_strengths()

                # current_community = _starting_community()
                current_community = _starting_community(evidence_embedding)
                if current_community is None:
                    return

                print(f"\nTrial {trial} start: {current_community}")

                for step in range(1, steps_per_trial + 1):
                    walk_name, walk_function, _ = RNG.choices(
                        walk_options,
                        weights=[weight for _, _, weight in walk_options],
                        k=1,
                    )[0]
                    # per community is here
                    _compare_similarity_at_walk(
                        current_community=current_community,
                        evidence_text=evidence_text,
                        evidence_embedding=evidence_embedding,
                        path_confidence=0.9 ** (step - 1)
                    )


                    if walk_name == "levy jump":
                        next_community = walk_function()
                    else:
                        next_community = walk_function(current_community)

                    if next_community is None:
                        print(
                            f"Trial {trial}, step {step}: {walk_name} from "
                            f"{current_community} -> no available move"
                        )
                        continue

                    print(
                        f"Trial {trial}, step {step}: {walk_name} from "
                        f"{current_community} -> {next_community}"
                    )
                    current_community = next_community
    
if __name__ == "__main__":
    start = time.time()
    # _ontology_embedding_similarity()
    # _summary_embedding_similarity()

    # concept_class = URIRef("http://example.org/3dui-ontology#Task")
    # print(_adjacent_walk(concept_class))

    walk(trial_count=3, steps_per_trial=10)
    # cache["items"][str(EX.TravelTechnique)]["embedding"]

    # _compare_similarity_at_walk(EX.TravelTechnique)

    end = time.time()
    print(f"Finished in: {end - start}")

"""
07/10/26: for the community embeddings, do not embed 

Community: Task
Label: Task
Comment: A unit of work that a user seeks to accomplish within a 3D user interface.
Subclass of: Domain Concept
Relation: Task | owl:disjointWith | Design Principle
Relation: Task | owl:disjointWith | Evaluation Method
Relation: Task | owl:disjointWith | UI Component
Relation: Task | rdf:type | owl:Class VS A unit of work that can involve practical warehouse optimization using virtual reality

it's metadata dilution

CHANGE TO: 
Task. A unit of work that a user seeks to accomplish within a 3D user interface.

the relations are useful but it answers "where does this class sit in the ontology. They should be scored separately?
"""

# after these runs, use LLMs to look into hotspots
# split summary into two files (one for hierarchal reconstruction and one for additional evidence?)
# so that the embeddings don't get polluted with hierarchy construction data: but how do u differentiate even...
