from functools import cache
from pathlib import Path
import pickle
import random

import numpy as np
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

import hnswlib

try:
    from src.preprocessing import get_embedding_model
    from src import config
except ModuleNotFoundError:
    from preprocessing import get_embedding_model
    import config

ONTOLOGY_EMBEDDING_CACHE_PATH = Path("_preprocessed/community_embeddings.pkl")
ONTOLOGY_HNSW_INDEX_PATH = Path("_preprocessed/community_hnsw.bin")


g = Graph()
g.parse("_raw_inputs/simplified_xr.ttl", format="ttl")
RNG = random.Random(11)


@cache
def _ontology_cache() -> dict:
    """Loaded once; holds per-community semantic/structure embeddings."""
    with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as f:
        return pickle.load(f)


def _seed_random_comm(communities: list[URIRef]) -> URIRef:
    return RNG.choice(communities)

# to be deprecated, use HNSW
def _get_communities() -> list[URIRef]:
    concept_class = URIRef("http://example.org/3dui-ontology#Concept")
    return [
        community
        for community in g.transitive_subjects(RDFS.subClassOf, concept_class)
        if isinstance(community, URIRef) and community != concept_class
    ]

def _hnsw_picks(evidence_embedding) -> list[URIRef]:
    dim = len(evidence_embedding)
    index = hnswlib.Index(space="cosine", dim=dim)
    index.load_index(str(ONTOLOGY_HNSW_INDEX_PATH))
    # Set the query-time accuracy/speed tradeoff after loading
    index.set_ef(50)

    # goes off of whatever dimension is in evidence_embedding
    query = np.asarray(evidence_embedding).reshape(1, -1)
    labels, distances = index.knn_query(query, k=3) # THIS LINE GETS TOP K RESULTS

    uris = _ontology_cache()["uris"]

    return [URIRef(uris[label]) for label in labels[0]]

def _starting_community(evidence_embedding) -> URIRef | None:
    # communities = _get_communities()
    communities = _hnsw_picks(evidence_embedding)

    if communities:
        random_community = _seed_random_comm(communities=communities)
        print(f"Randomly selected community: {random_community}")
        return random_community
        # return communities
    else:
        print("No communities found in the ontology.")
        return None


# --- Shared topology helpers ------------------------------------------------
def _direct_children(current_community) -> list[URIRef]:
    return [
        child
        for child in g.subjects(RDFS.subClassOf, current_community)
        if isinstance(child, URIRef)
    ]


def _siblings(current_community) -> list[URIRef]:
    """node's parents, then the parents' other children."""
    siblings = set()
    for parent in g.objects(current_community, RDFS.subClassOf):
        for sibling in g.subjects(RDFS.subClassOf, parent):
            if isinstance(sibling, URIRef) and sibling != current_community:
                siblings.add(sibling)
    return list(siblings)


def _adjacent_walk(current_community) -> URIRef | None:
    """must get node's parents, and then examine its children"""
    siblings = _siblings(current_community)
    if not siblings:
        return None
    return _seed_random_comm(siblings)

def _direct_child_walk(current_community) -> URIRef | None:
    children = _direct_children(current_community)
    if not children:
        return None
    return _seed_random_comm(children)

def _levy_jump() -> URIRef | None:
    connected_communities = [
        community
        for community in _get_communities()
        if any(g.triples((community, None, None)))
        or any(g.triples((None, None, community)))
    ]

    if not connected_communities:
        return None
    return _seed_random_comm(connected_communities)


# --- Pheromone-biased move (closes the stigmergy loop) ----------------------
def _eta(evidence_embedding, community: URIRef) -> float:
    """Heuristic desirability: embedding similarity(evidence, community).

    Clamped to a small positive floor because eta ** BETA is undefined for a
    negative base with a non-integer exponent.
    """
    item = _ontology_cache()["items"].get(str(community))
    if item is None:
        return 1e-6
    score = get_embedding_model().similarity(
        evidence_embedding, item["semantic_embedding"]
    ).item()
    return max(score, 1e-6)


def _pheromone_biased_walk(
    current_community,
    evidence_embedding,
    blackboard_strengths: dict[str, float],
) -> URIRef | None:
    """Sample the next community with probability proportional to
    tau^ALPHA * eta^BETA over the structural neighbourhood.

    tau is read from the blackboard (with a TAU_INIT floor so an empty board
    falls back to pure eta), eta is the live embedding similarity to the current
    evidence. With probability LEVY_EPSILON take a random restart instead.
    """
    if RNG.random() < config.LEVY_EPSILON:
        return _levy_jump()

    candidates = list(
        set(_direct_children(current_community)) | set(_siblings(current_community))
    )
    if current_community in candidates:
        candidates.remove(current_community)
    if not candidates:
        return _levy_jump()

    weights = []
    for candidate in candidates:
        eta = _eta(evidence_embedding, candidate)
        tau = config.TAU_INIT + blackboard_strengths.get(str(candidate), 0.0)
        weights.append((tau ** config.ALPHA) * (eta ** config.BETA))

    if sum(weights) <= 0:
        return _seed_random_comm(candidates)
    return RNG.choices(candidates, weights=weights, k=1)[0]


if __name__ == "__main__":
    sample_evidence = "fast virtual reality movement causes cybersickness"
    embedding = get_embedding_model().encode(sample_evidence)
    print(_hnsw_picks(embedding))
