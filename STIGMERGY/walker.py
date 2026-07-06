"""
pick a new start to the node every time
do the stateless random walk. 

every node: cheap embedding similarity (modified TTL v. summary)
- comparing modified_original TTL community to summary.txt file
high scoring nodes: cached LLM sniff/proposal
"""
import time
from pathlib import Path
import pickle
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS
import random
from sentence_transformers import SentenceTransformer

ONTOLOGY_EMBEDDING_CACHE_PATH = Path("community_embeddings.pkl")
SUMMARY_EMBEDDING_CACHE_PATH = Path("summary_embeddings.pkl")
MAIN_ONTOLOGY = Path("simplified_xr.ttl")
SUMMARY = Path("summary.txt")

def _seed_random_comm(communities):
    random.seed(10)
    return random.choice(communities)

""" creates embeddings of each community in the main ontology
        - embedding coordinates are cached in .pkl file "community_embeddings" """
def _ontology_embedding_similarity():
    """ extract label, comment, direct subClass, other (s,p,o) relationships in a structured format
    for ALL communities
    format: 
        Community: Evaluation Method
        Label: Evaluation Method
        Comment: Methodologies used to assess the usability, performance, or user experience of 3D UIs.
        Subclass of: Domain Concept
        Relation: Evaluation Method | owl:disjointWith | Design Principle
        Relation: Evaluation Method | rdf:type | owl:Class """
    def _extract_TTL_community_context() -> list[str]:
        graph = Graph()
        graph.parse(MAIN_ONTOLOGY, format="ttl")

        concept_class = URIRef("http://example.org/3dui-ontology#Concept")
        communities = [
            community
            for community in graph.transitive_subjects(RDFS.subClassOf, concept_class)
            if community != concept_class
        ]

        labels = {
            subject: str(label)
            for subject, label in graph.subject_objects(RDFS.label)
        }

        def _name(node):
            if node in labels:
                return labels[node]
            if isinstance(node, URIRef):
                return graph.namespace_manager.normalizeUri(node)
            return str(node)

        community_contexts = []
        explicit_predicates = {RDFS.label, RDFS.comment, RDFS.subClassOf}

        for community in communities:
            lines = [f"Community: {_name(community)}"]

            for label in graph.objects(community, RDFS.label):
                lines.append(f"Label: {label}")
            for comment in graph.objects(community, RDFS.comment):
                lines.append(f"Comment: {comment}")
            for parent in graph.objects(community, RDFS.subClassOf):
                lines.append(f"Subclass of: {_name(parent)}")

            other_relations = [
                f"Relation: {_name(subject)} | {_name(predicate)} | {_name(obj)}"
                for subject, predicate, obj in graph.triples((community, None, None))
                if predicate not in explicit_predicates
            ]
            lines.extend(sorted(other_relations))
            community_contexts.append("\n".join(lines))

        return community_contexts

    descriptions = _extract_TTL_community_context()

    def write_to_cache():
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        embeddings = model.encode(descriptions)
        with ONTOLOGY_EMBEDDING_CACHE_PATH.open("wb") as f:
            pickle.dump(
                {
                    "descriptions": descriptions,
                    "embeddings": embeddings
                }, 
                f,
            )

    if ONTOLOGY_EMBEDDING_CACHE_PATH.exists():
        with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as f:
            cached = pickle.load(f)
        if cached["descriptions"] == descriptions: # no change, just load embeddings from cache
            embeddings = cached["embeddings"]
        else: # update it if raw descriptions are different
            write_to_cache()
    else:
        write_to_cache()

    """
    # FOR COMPARISONS
    # comparing the same text to itself should give 1.0 since it's maximally close to itself
    """
    # similarities = model.similarity(embeddings, embeddings)
    # print(similarities)
    """
    For printing out first n embedding coordinates
    """
    # for i, embedding in enumerate(embeddings):
    #     print(f"Description {i}: {descriptions[i]}")
    #     print(embedding[:10]) 

""" takes in summary.txt, reads line by line then generates embedding per line"""
def _summary_embedding_similarity():

    """ in summary.txt, each line is its own evidence, must embed per """
    def _extract_summary_txt() -> list[str]:
        summary_evidence = []
        with open(SUMMARY, 'r', encoding="utf-8") as f:
            for line in f:
                clean_strip = line.rstrip('\n')
                summary_evidence.append(clean_strip)
        return summary_evidence
        
    descriptions = _extract_summary_txt()

    def write_to_cache():
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        embeddings = model.encode(descriptions)
        with SUMMARY_EMBEDDING_CACHE_PATH.open("wb") as f:
            pickle.dump(
                {
                    "descriptions": descriptions,
                    "embeddings": embeddings
                }, 
                f,
            )
    if SUMMARY_EMBEDDING_CACHE_PATH.exists():
        with SUMMARY_EMBEDDING_CACHE_PATH.open("rb") as f:
            cached = pickle.load(f)
        if cached["descriptions"] == descriptions: # no change, just load embeddings from cache
            embeddings = cached["embeddings"]
        else: # update it if raw descriptions are different
            write_to_cache()
    else:
        write_to_cache()

if __name__ == "__main__":
    start = time.time()

    _ontology_embedding_similarity()
    _summary_embedding_similarity()

    end = time.time()
    print(f"Finished in: {end - start}")


# g = Graph()
# g.parse("simplified_xr.ttl", format="ttl")

# concept_class = URIRef("http://example.org/3dui-ontology#Concept")

# communities = list(g.transitive_subjects(RDFS.subClassOf, concept_class))
# # exclude the :Concept itself
# communities.remove(concept_class)

# # print(communities)

# if communities:
#     random_community = _seed_random_comm(communities=communities)
#     print(f"Randomly selected community: {random_community}")
# else:
#     print("No communities found in the ontology.")
