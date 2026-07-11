"""
pick a new start to the node every time
do the stateless random walk. 

every node: cheap embedding similarity (modified TTL v. summary)
- comparing modified_original TTL community to summary.txt file
high scoring nodes: cached LLM sniff/proposal
"""
from __future__ import annotations

import time
from pathlib import Path
import numpy as np
import pickle
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS
from sentence_transformers import SentenceTransformer

from llm.lmstudio_llm import LMStudioLLM
from walk_strategies import (
    RNG,
    _adjacent_walk,
    _direct_child_walk,
    _levy_jump,
    _starting_community,
)

ONTOLOGY_EMBEDDING_CACHE_PATH = Path("_preprocessed/community_embeddings.pkl")
SUMMARY_EMBEDDING_CACHE_PATH = Path("_preprocessed/summary_embeddings.pkl")
MAIN_ONTOLOGY = Path("_raw_inputs/simplified_xr.ttl")
SUMMARY = Path("_raw_inputs/summary.txt")

EX = Namespace("http://example.org/3dui-ontology#")

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

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
        # def _name(node):
        #     if node in labels:
        #         return labels[node]
        #     if isinstance(node, URIRef):
        #         return graph.namespace_manager.normalizeUri(node)
        #     return str(node)

        # community_contexts = []
        # explicit_predicates = {RDFS.label, RDFS.comment, RDFS.subClassOf}

        # for community in communities:
        #     lines = [f"Community: {_name(community)}"]

        #     for label in graph.objects(community, RDFS.label):
        #         lines.append(f"Label: {label}")
        #     for comment in graph.objects(community, RDFS.comment):
        #         lines.append(f"Comment: {comment}")
        #     for parent in graph.objects(community, RDFS.subClassOf):
        #         lines.append(f"Subclass of: {_name(parent)}")

        #     other_relations = [
        #         f"Relation: {_name(subject)} | {_name(predicate)} | {_name(obj)}"
        #         for subject, predicate, obj in graph.triples((community, None, None))
        #         if predicate not in explicit_predicates
        #     ]
        #     lines.extend(sorted(other_relations))
        #     community_contexts.append("\n".join(lines))

        # return communities, community_contexts

    community_uris, semantic_descriptions, structure_descriptions = (
        _extract_TTL_community_context()
    )

    def write_to_cache():
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        semantic_embeddings = model.encode(semantic_descriptions)
        structure_embeddings = model.encode(structure_descriptions)

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
            "model": "BAAI/bge-small-en-v1.5",
            "uris": [str(uri) for uri in community_uris],
            "items": items,
        }

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

def _generate_llm_relational_description(ontology, evidence):
    llm = LMStudioLLM() # swap with NVIDIANIMLLM if needed
    response = llm.send_messages(
        f"""
            Evidence 1: {ontology}
            Evidence 2: {evidence}
        """
    )
    return response

def _compare_similarity_at_walk(current_community, semantic_weight=0.85):
    structure_weight = 1.0 - semantic_weight

    with (
        SUMMARY_EMBEDDING_CACHE_PATH.open("rb") as sum_embed,
        ONTOLOGY_EMBEDDING_CACHE_PATH.open("rb") as ont_embed,
    ):
        summaries = pickle.load(sum_embed)
        ontology = pickle.load(ont_embed)

        descriptions = summaries["descriptions"]
        embeddings = summaries["embeddings"]

        community = ontology["items"][str(current_community)]
        semantic_embedding = community["semantic_embedding"]
        structure_embedding = community["structure_embedding"]
        for description, embedding in zip(descriptions, embeddings):
            semantic_score = model.similarity(embedding, semantic_embedding).item()
            structure_score = model.similarity(embedding, structure_embedding).item()
            final_score = (
                semantic_weight * semantic_score
                + structure_weight * structure_score
            )
            print(
                f"semantic={semantic_score:.4f} "
                f"structure={structure_score:.4f} "
                f"final={final_score:.4f}\n"
                f"Semantic text: {community['semantic_description']}\n"
                f"Structure text: {community['structure_description']}\n"
                f"Summary text: {description}\n"
            )
            
            if final_score > 0.6:
                ontology = f"""
                    Semantic text: {community['semantic_description']}
                    Structure text: {community['structure_description']}
                """
                response = _generate_llm_relational_description(ontology=ontology, evidence=description)
                print(response)


# Random-walk orchestration.
def walk(trial_count=5, steps_per_trial=10):
    walk_options = [
        ("top down", _direct_child_walk, 0.6),
        ("adjacent", _adjacent_walk, 0.3),
        ("levy jump", _levy_jump, 0.1),
    ]

    for trial in range(1, trial_count + 1):
        current_community = _starting_community()
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
            _compare_similarity_at_walk(current_community=current_community)


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
