from pathlib import Path
import pickle
import random

import numpy as np
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

import hnswlib

try:
    from src.preprocessing import get_embedding_model
except ModuleNotFoundError:
    from preprocessing import get_embedding_model

ONTOLOGY_EMBEDDING_CACHE_PATH = Path("_preprocessed/community_embeddings.pkl")
ONTOLOGY_HNSW_INDEX_PATH = Path("_preprocessed/community_hnsw.bin")


g = Graph()
g.parse("_raw_inputs/simplified_xr.ttl", format="ttl")
RNG = random.Random(11)


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

    with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as f:
        cache = pickle.load(f)
    
    uris = cache["uris"]

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

def _adjacent_walk(current_community) -> URIRef | None:
    """must get node's parents, and then examine its children"""
    def get_siblings() -> list[URIRef]:
        siblings = set()
        parents = g.objects(current_community, RDFS.subClassOf)

        for parent in parents:
            # find all direct children of that parent
            for sibling in g.subjects(RDFS.subClassOf, parent):
                if isinstance(sibling, URIRef) and sibling != current_community:
                    siblings.add(sibling)
        return list(siblings)

    siblings = get_siblings()
    if not siblings:
        return None
    return _seed_random_comm(siblings)
    
def _direct_child_walk(current_community) -> URIRef | None:
    children = [
        child
        for child in g.subjects(RDFS.subClassOf, current_community)
        if isinstance(child, URIRef)
    ]
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


if __name__ == "__main__":
    sample_evidence = "fast virtual reality movement causes cybersickness"
    embedding = get_embedding_model().encode(sample_evidence)
    print(_hnsw_picks(embedding))
