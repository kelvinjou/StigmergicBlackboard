from textwrap import dedent


EVIDENCE_RULES = dedent(
    """
    Reconstruction rules:
    - Reconstruct the missing RDF subgraph, not only its class hierarchy.
    - Include non-hierarchical predicates when the summary, current ontology,
      or tool observations provide concrete support for the assertion.
    - Restore both outgoing assertions from reconstructed resources and incoming
      assertions from retained resources.
    - Do not convert conceptual, possible, implied, schema-ready, or suggested
      relationships into asserted triples.
    - Reuse identifiers and predicates from the current ontology.
    - Do not repeat triples already present in the current ontology.
    """
).strip()
