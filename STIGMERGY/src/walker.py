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
from src import config
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
    _pheromone_biased_walk,
    _starting_community,
)

BLACKBOARD_DIR = Path("_raw_outputs")

EX = Namespace("http://example.org/3dui-ontology#")

def _blackboard_path(evidence_index: int) -> Path:
    return BLACKBOARD_DIR / f"bb{evidence_index}.jsonl"


def _reset_blackboard(blackboard_path: Path):
    blackboard_path.parent.mkdir(parents=True, exist_ok=True)
    blackboard_path.write_text("", encoding="utf8")


def _decay_blackboard_strengths(blackboard_path: Path, decay=None):
    """Evaporate pheromone (tau) once per trial: tau <- (1 - rho) * tau."""
    if decay is None:
        decay = 1.0 - config.EVAPORATION_RATE
    blackboard_items = _load_blackboard_items(blackboard_path)

    for item in blackboard_items.values():
        item["strength"] *= decay

    _write_blackboard_items(blackboard_path, blackboard_items)


def _blackboard_strengths(blackboard_path: Path) -> dict[str, float]:
    """{community_id: tau} snapshot the walk reads to bias the next step."""
    return {
        community_id: item.get("strength", 0.0)
        for community_id, item in _load_blackboard_items(blackboard_path).items()
    }


def _append_blackboard_blurb(
    blackboard_path,
    community_id,
    community,
    heuristic,
    path_confidence,
    evidence,
    blurb,
):
    """Deposit pheromone and record the blurb.

    tau (item["strength"]) is the LEARNED pheromone. It is deliberately NOT the
    raw embedding score: the deposit uses diminishing returns per
    (evidence, community) pair so repeated identical landings saturate, while
    accumulation ACROSS different evidence stays the real signal. eta (the raw
    embedding score) is kept per-blurb under "heuristic".
    """
    blackboard_items = _load_blackboard_items(blackboard_path)

    if community_id not in blackboard_items:
        blackboard_items[community_id] = {
            "id": str(uuid.uuid4()),
            "community_id": community_id,
            "community": community["semantic_description"],
            "strength": 0.0,
            "visits": {},
            "blurb": [],
        }

    item = blackboard_items[community_id]

    # base deposit: relevance-weighted (eta) or a constant per visit
    if config.DEPOSIT_MODE == "constant":
        base = config.CONSTANT_DEPOSIT_Q * path_confidence
    else:
        base = heuristic * path_confidence

    # diminishing returns for repeated (evidence, community) landings
    prior_visits = item["visits"].get(evidence, 0)
    deposit = base * (config.DIMINISHING_RETURNS ** prior_visits)
    item["visits"][evidence] = prior_visits + 1

    item["strength"] += deposit

    item["blurb"].append(
        {
            "evidence": evidence,
            "text": blurb,
            "heuristic": heuristic,
            "deposit": deposit,
        }
    )
    _write_blackboard_items(blackboard_path, blackboard_items)

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
    blackboard_path,
    path_confidence=1.0,
    semantic_weight=None,
):
    if semantic_weight is None:
        semantic_weight = config.SEMANTIC_WEIGHT
    structure_weight = 1.0 - semantic_weight

    with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as ont_embed:
        ontology = pickle.load(ont_embed)

        community = ontology["items"][str(current_community)]
        semantic_embedding = community["semantic_embedding"]
        structure_embedding = community["structure_embedding"]

        semantic_score = get_embedding_model().similarity(evidence_embedding, semantic_embedding).item()
        structure_score = get_embedding_model().similarity(evidence_embedding, structure_embedding).item()
        # eta: heuristic desirability (static, per-evidence). NOT the pheromone.
        heuristic = (
            semantic_weight * semantic_score
            + structure_weight * structure_score
        )
        print(
            f"semantic={semantic_score:.4f} "
            f"structure={structure_score:.4f} "
            f"eta={heuristic:.4f} path_conf={path_confidence:.4f}\n"
            f"Semantic text: {community['semantic_description']}\n"
            f"Structure text: {community['structure_description']}\n"
            f"Summary text: {evidence_text}\n"
        )

        if heuristic > config.BLURB_THRESHOLD:
            ontology = f"""
                Semantic text: {community['semantic_description']}
                Structure text: {community['structure_description']}
            """
            blurb = _generate_llm_relational_description(ontology=ontology, evidence=evidence_text)
            if blurb is None:
                print("Something went wrong? Perchance")
                return


            _append_blackboard_blurb(
                blackboard_path=blackboard_path,
                community_id=str(current_community),
                community=community,
                heuristic=heuristic,
                path_confidence=path_confidence,
                evidence=evidence_text,
                blurb=blurb,
            )


# Random-walk orchestration. 
# walk now owns the evidence loop
def walk(trial_count=5, steps_per_trial=10):
    walk_options = [
        ("top down", _direct_child_walk, config.TOP_DOWN_WEIGHT),
        ("adjacent", _adjacent_walk, config.ADJACENT_WEIGHT),
        ("levy jump", _levy_jump, config.LEVY_WEIGHT),
    ]


    with (
        SUMMARY_EMBEDDING_CACHE_PATH.open("rb") as sum_embed
    ):
        summaries = pickle.load(sum_embed)
        for evidence_index, (evidence_text, evidence_embedding) in enumerate(zip(
            summaries["descriptions"],
            summaries["embeddings"]
        ), start=1):
            blackboard_path = _blackboard_path(evidence_index)
            _reset_blackboard(blackboard_path)
            print(f"\nEvidence {evidence_index}: writing blackboard to {blackboard_path}")

            for trial in range(1, trial_count + 1):
                _decay_blackboard_strengths(blackboard_path)

                # current_community = _starting_community()
                current_community = _starting_community(evidence_embedding)
                if current_community is None:
                    return

                print(f"\nTrial {trial} start: {current_community}")

                for step in range(1, steps_per_trial + 1):
                    path_confidence = config.PATH_CONFIDENCE_DECAY ** (step - 1)
                    # score (and possibly deposit on) the current community
                    _compare_similarity_at_walk(
                        current_community=current_community,
                        evidence_text=evidence_text,
                        evidence_embedding=evidence_embedding,
                        blackboard_path=blackboard_path,
                        path_confidence=path_confidence,
                    )

                    # choose the next community
                    if config.PHEROMONE_BIAS_ENABLED:
                        # closed loop: read tau off the blackboard, bias by
                        # tau^ALPHA * eta^BETA
                        walk_name = "pheromone-biased"
                        next_community = _pheromone_biased_walk(
                            current_community,
                            evidence_embedding,
                            _blackboard_strengths(blackboard_path),
                        )
                    else:
                        # ablation: fixed-weight strategy + uniform-random node
                        walk_name, walk_function, _ = RNG.choices(
                            walk_options,
                            weights=[weight for _, _, weight in walk_options],
                            k=1,
                        )[0]
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

                # score the final landing (previously never scored)
                _compare_similarity_at_walk(
                    current_community=current_community,
                    evidence_text=evidence_text,
                    evidence_embedding=evidence_embedding,
                    blackboard_path=blackboard_path,
                    path_confidence=config.PATH_CONFIDENCE_DECAY ** steps_per_trial,
                )
    
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
