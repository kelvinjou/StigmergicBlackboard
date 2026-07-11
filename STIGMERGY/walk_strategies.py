import random

from rdflib import Graph, URIRef
from rdflib.namespace import RDFS


g = Graph()
g.parse("_raw_inputs/simplified_xr.ttl", format="ttl")
RNG = random.Random(10)


def _seed_random_comm(communities: list[URIRef]) -> URIRef:
    return RNG.choice(communities)

def _get_communities() -> list[URIRef]:
    concept_class = URIRef("http://example.org/3dui-ontology#Concept")
    return [
        community
        for community in g.transitive_subjects(RDFS.subClassOf, concept_class)
        if isinstance(community, URIRef) and community != concept_class
    ]

def _starting_community() -> URIRef | None:
    communities = _get_communities()

    if communities:
        random_community = _seed_random_comm(communities=communities)
        print(f"Randomly selected community: {random_community}")
        return random_community
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
