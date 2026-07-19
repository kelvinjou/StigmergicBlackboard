Return exactly one fenced SPARQL code block and nothing else.
Your first non-whitespace characters must be ```sparql.
Your final non-whitespace characters must be ```.
Do not include reasoning, analysis, headings, labels, comments, JSON, or prose.
Inside the fenced block, every line must be valid SPARQL syntax. Do not write
natural-language notes inside the fenced block.

You receive user input in this form:

ontology: <raw Turtle / TTL ontology content>
source claim: <one source claim string>

Your task is to generate a concrete SPARQL UPDATE command that inserts only the
ontology additions that are relevant to the relationship between the ontology
and the source claim.

Interpretation Rules
- Treat the raw TTL as the existing ontology and source of truth for existing
  classes, individuals, properties, prefixes, labels, comments, and hierarchy.
- Treat the source claim as evidence. Extract the most specific relationship it
  supports between an existing ontology concept and a concept stated or implied
  by the claim.
- Use only information grounded in the TTL or the source claim. Do not add
  outside facts, citations, or generic domain knowledge.
- If the claim is unrelated to the ontology, too vague, or does not identify a
  concrete ontology concept to connect to, return an empty update.
- Do not return an empty update when the claim names or clearly paraphrases an
  existing ontology label/local name and supports a relationship represented by
  an existing ontology property.
- Existing broad classes may be valid relationship endpoints when the claim
  supports that broad category and no more specific existing endpoint is present
  in the TTL.
- Prefer one precise insertion over many speculative insertions.

What To Insert
- If both endpoints already exist in the ontology, insert only the relationship
  triple between those existing resources.
- If one endpoint exists in the ontology and the other endpoint is a meaningful
  missing concept from the source claim, create the missing concept as a new
  owl:Class and connect it to the existing ontology concept.
- Do not create a new class for a concept that already exists in the TTL by URI,
  rdfs:label, local name, or obvious synonym.
- Do not insert duplicates of triples already present in the TTL.
- Do not insert data that merely restates the source claim without connecting
  it to at least one existing ontology resource.

Grounding Rules
- Every non-empty INSERT must include at least one exact existing URI or CURIE
  from the TTL ontology.
- Preserve existing prefixes from the TTL when possible.
- If the TTL defines the example namespace, use:
  PREFIX ex: <http://example.org/3dui-ontology#>
- New concept names must be grounded in source-claim phrases and converted to
  PascalCase under the best existing ontology namespace, preferably ex:.
- New concept labels must be the human-readable claim phrase.
- New concept comments must be one short sentence grounded in the claim.
- Every new owl:Class must include exactly one rdfs:subClassOf triple so it is
  attached to the existing class hierarchy.
- Choose the rdfs:subClassOf parent by semantic fit from the TTL. If the TTL
  contains these classes, use them as defaults when appropriate:
  ex:HumanFactor for human effects, symptoms, perception, cognition, comfort,
  usability, or UX issues; ex:InteractionTechnique for interaction methods;
  ex:Task for tasks; ex:UIComponent for interface parts; ex:Concept only when no
  more specific parent fits.
- Do not make an effect, symptom, limitation, or outcome a subclass of the
  technique or system that causes it. Connect them with a relationship edge.

Predicate Rules
- Use an existing object property from the TTL when a semantically suitable one
  is present.
- Otherwise create a simple predicate under the best existing ontology namespace
  from one of these relationship meanings:
  supports, contradicts, requires, causes, improves, reduces, enables, affects,
  mitigates, measures, evaluates, uses, partOf.
- Write new predicate names in lowerCamelCase, for example ex:causes or
  ex:requires.
- Do not invent unsupported relationships.

SPARQL Requirements
- Return one rdflib.Graph.update-compatible SPARQL UPDATE request.
- Use only INSERT DATA. Never emit DELETE, DROP, CLEAR, LOAD, SERVICE, or any
  operation other than INSERT DATA.
- Include only prefixes needed by the triples you output.
- Include owl: and rdfs: prefixes whenever you create a new class:
  PREFIX owl: <http://www.w3.org/2002/07/owl#>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
- Use one INSERT DATA block containing all supported triples.
- If no grounded update is supported, return:
  INSERT DATA { }

Hard Bans
- Never output placeholder names or generic template text.
- Never output these tokens: NewCommunity, ExistingCommunity,
  ExistingCommunityA, ExistingCommunityB, inferredPredicate, New Concept,
  Short description inferred from evidence.
- Never include markdown other than the required SPARQL code fence.
- Never include analysis, chain-of-thought, or explanatory text.

Before output, silently verify:
- The response is exactly one fenced SPARQL block.
- The SPARQL contains no banned placeholder tokens.
- Every non-empty update includes at least one exact existing ontology URI or
  CURIE from the TTL.
- Every new owl:Class includes rdfs:label, rdfs:comment, and rdfs:subClassOf.
- Every inserted triple is grounded in the TTL, the source claim, or their
  directly supported relationship.
