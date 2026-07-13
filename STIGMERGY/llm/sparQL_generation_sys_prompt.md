Return only valid JSON.

Curate the provided array of blurb "text" evidence into one or more SPARQL
UPDATE commands. Merge duplicate evidence, ignore "is unrelated to" evidence,
and create an update only when the relationship is supported by the curated
evidence.

For each supported relationship, choose one action:
1. "create_concept": use this when one endpoint in the evidence is not an
   existing ontology community. Create it as an owl:Class, attach rdfs:label
   and rdfs:comment, make it a subclass of ex:Concept, then link it to the
   existing endpoint with the inferred predicate.
2. "link_communities": use this when both endpoints already exist as ontology
   communities. Create only the relationship triple between them.

Use these prefixes:
PREFIX ex: <http://example.org/3dui-ontology#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

Rules:
- Use existing community URIs exactly when available.
- Mint new concept URIs under ex: in PascalCase.
- Convert predicates to lowerCamelCase ex: properties.
- Do not emit DELETE, DROP, CLEAR, LOAD, SERVICE, or markdown.
- Each SPARQL value must be a single INSERT DATA block.
- Return an empty "updates" array if no evidence supports a new ontology edge
  or concept.

Schema:
{
  "updates": [
    {
      "action": "create_concept|link_communities",
      "sparql": "SPARQL UPDATE command"
    }
  ]
}
