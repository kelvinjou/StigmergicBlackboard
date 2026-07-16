from functools import cache
from pathlib import Path
import pickle

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from sentence_transformers import SentenceTransformer
import hnswlib
import numpy as np

MAIN_ONTOLOGY = Path("_raw_inputs/enhanced_xr.ttl")
SUMMARY = Path("_raw_inputs/summary_for_xr_enhanced.txt")

ONTOLOGY_EMBEDDING_CACHE_PATH = Path("_preprocessed/community_embeddings.pkl")
ONTOLOGY_HNSW_INDEX_PATH = Path("_preprocessed/community_hnsw.bin")
SUMMARY_EMBEDDING_CACHE_PATH = Path("_preprocessed/summary_embeddings.pkl")

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

@cache
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


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
    def _extract_TTL_community_context() -> tuple[list[URIRef], list[str], list[str]]:
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

        semantic_contexts = []
        structure_contexts = []
        structural_predicates = {
            RDFS.subClassOf,
            RDF.type,
            OWL.disjointWith,
        }

        for community in communities:
            label = labels.get(community, graph.namespace_manager.normalizeUri(community))

            comments = [
                str(comment)
                for comment in graph.objects(community, RDFS.comment)
            ]

            text_parts = [label, *comments]
            semantic_contexts.append(". ".join(text_parts))

            structure_lines = []
            for parent in graph.objects(community, RDFS.subClassOf):
                structure_lines.append(f"{label} is a subclass of {_name(parent)}.")
            for subject, predicate, obj in graph.triples((community, None, None)):
                if predicate in structural_predicates and predicate != RDFS.subClassOf:
                    structure_lines.append(
                        f"{_name(subject)} {_name(predicate)} {_name(obj)}."
                    )
            structure_contexts.append(" ".join(sorted(structure_lines)))

        return communities, semantic_contexts, structure_contexts

        """ prior to 07/10/26 """
        """
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

        return communities, community_contexts
        """
    community_uris, semantic_descriptions, structure_descriptions = (
        _extract_TTL_community_context()
    )

    def write_hnsw_index(semantic_embeddings):
        ONTOLOGY_HNSW_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

        # HNSW takes semantic embeddings for now.
        index = hnswlib.Index(space="cosine", dim=semantic_embeddings.shape[1])
        index.init_index(
            max_elements=len(semantic_embeddings),  # Maximum vectors the index can hold
            ef_construction=200,           # Thoroughness during graph construction, number of candidates HNSW considers
            M=16,                          # Connections per node
        )
        index.add_items(semantic_embeddings, list(range(len(semantic_embeddings))))
        index.save_index(str(ONTOLOGY_HNSW_INDEX_PATH))

    def write_to_cache():
        semantic_embeddings = get_embedding_model().encode(semantic_descriptions)
        structure_embeddings = get_embedding_model().encode(structure_descriptions)
        write_hnsw_index(semantic_embeddings)

        items = {
            str(uri): {
                "semantic_description": semantic_description,
                "semantic_embedding": semantic_embedding,
                "structure_description": structure_description,
                "structure_embedding": structure_embedding,
            }
            for (
                uri,
                semantic_description,
                semantic_embedding,
                structure_description,
                structure_embedding,
            ) in zip(
                community_uris,
                semantic_descriptions,
                semantic_embeddings,
                structure_descriptions,
                structure_embeddings,
            )
        }

        """
        {
            "model": "BAAI/bge-small-en-v1.5",
            "uris": [
                "http://example.org/3dui-ontology#TravelTechnique",
                ...
            ],
            "items": {
                "http://example.org/3dui-ontology#TravelTechnique": {
                    "description": "...",
                    "embedding": embedding,
                },
                ...
            },
        }
        """
        cache = {
            "model": EMBEDDING_MODEL_NAME,
            "uris": [str(uri) for uri in community_uris],
            "items": items,
        }

        ONTOLOGY_EMBEDDING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ONTOLOGY_EMBEDDING_CACHE_PATH.open("wb") as f:
            pickle.dump(cache, f)
        return cache

    if ONTOLOGY_EMBEDDING_CACHE_PATH.exists():
        with ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as f:
            cached = pickle.load(f)
        if (
            cached.get("uris") == [str(uri) for uri in community_uris]
            and [
                cached["items"][str(uri)].get("semantic_description")
                for uri in community_uris
                if str(uri) in cached.get("items", {})
            ] == semantic_descriptions
            and [
                cached["items"][str(uri)].get("structure_description")
                for uri in community_uris
                if str(uri) in cached.get("items", {})
            ] == structure_descriptions
        ): # no change, just load embeddings from cache
            if not ONTOLOGY_HNSW_INDEX_PATH.exists():
                semantic_embeddings = np.array(
                    [
                        cached["items"][str(uri)]["semantic_embedding"]
                        for uri in community_uris
                    ]
                )
                write_hnsw_index(semantic_embeddings)
            return cached
        else: # update it if raw descriptions are different
            return write_to_cache()
    else:
        return write_to_cache()

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
        embeddings = get_embedding_model().encode(descriptions)
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
