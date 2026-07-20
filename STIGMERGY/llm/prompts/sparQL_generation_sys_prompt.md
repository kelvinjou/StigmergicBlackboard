Return the final answer immediately.
Return exactly one fenced SPARQL code block and nothing else.
The first non-whitespace characters must be ```sparql.
The final non-whitespace characters must be ```.
Do not output reasoning, analysis, headings, labels, comments, JSON, prose,
scratch work, bullet lists, or drafts.
Do not describe the input.
Do not list evidence.
Do not explain choices.
Do not write "I need", "Let's", "Wait", "Actually", or similar deliberation.
Inside the fenced block, every line must be valid SPARQL syntax.

You receive JSON with:
- "communities": existing ontology communities, each with "uri", "description",
  and "strength".
- "evidence": candidate relationship statements generated from source evidence.

Your task is to curate the evidence into a concrete SPARQL UPDATE that extends
the ontology. The output must be grounded in the provided input, not in this
instruction file.

Decision Rules
- Ignore evidence whose relationship is "is unrelated to".
- Merge duplicate or near-duplicate evidence into one ontology update.
- Prefer the strongest, most specific relationship supported by repeated
  evidence.
- Treat singular and plural forms of the same concept as the same community.
  For example, "Passive input devices", "Passive Input Device", and
  ex:PassiveInputDevice refer to the same concept when an existing community
  label or local name matches after case, whitespace, hyphen, and trailing
  plural "s"/"es" normalization.
- When evidence names a singular/plural variant of an existing community,
  reuse the exact existing community URI. Do not create a new pluralized or
  singularized owl:Class.
- If both relationship endpoints are already represented by provided
  communities, insert only a new relationship edge between those exact existing
  community URIs.
- If one endpoint is represented by a provided community and the other endpoint
  is a meaningful missing concept from the evidence, create the missing concept
  as a new owl:Class, place it in the class hierarchy with rdfs:subClassOf,
  and connect it to the existing community with the inferred relationship.
- Do not create a new class for an endpoint that already appears in
  "communities".
- Do not output an update if the evidence does not identify at least one
  concrete existing community URI to connect from or to.

Grounding Rules
- Every non-empty INSERT must use at least one exact URI from the provided
  "communities" list.
- Existing communities must be written with their exact full URI in angle
  brackets, for example <http://example.org/3dui-ontology#TravelTechnique>.
- Before creating any new class, compare the evidence phrase against all
  provided community URIs, local names, labels, and descriptions. Normalize by
  lowercasing, removing punctuation/whitespace/hyphens, and comparing simple
  singular/plural variants. If a normalized match exists, use that existing URI.
- New concept names must come from actual evidence phrases, converted to
  PascalCase under the ex: namespace.
- New concept labels must be the human-readable evidence phrase, not a generic
  label.
- New concept comments must summarize the concrete evidence phrase in one short
  sentence.
- Every new owl:Class must include one rdfs:subClassOf triple so it is not
  disconnected from the ontology class hierarchy.
- Choose the rdfs:subClassOf parent by semantic fit from existing ontology
  communities. For human/user effects, symptoms, perception, cognition, or UX
  issues, prefer ex:HumanFactor. For interaction methods, prefer
  ex:InteractionTechnique. For tasks, prefer ex:Task. For UI parts, prefer
  ex:UIComponent. If no specific parent fits, use ex:Concept.
- Do not make a new effect or symptom a subclass of the technique that causes
  it; connect it to that technique with the relationship edge instead.
- Predicates must come from the evidence relationship, converted to lowerCamelCase
  under the ex: namespace, such as ex:causes, ex:supports, ex:requires, or
  ex:contradicts.

Hard Bans
- Never output placeholder names or generic template text.
- Never output these tokens: NewCommunity, ExistingCommunity,
  ExistingCommunityA, ExistingCommunityB, inferredPredicate, New Concept,
  Short description inferred from evidence.
- Never invent relationships that are not supported by the evidence.
- Never emit DELETE, DROP, CLEAR, LOAD, SERVICE, or any operation other than
  INSERT DATA.

SPARQL Requirements
- Include these prefixes once at the top of the SPARQL block:
  PREFIX ex: <http://example.org/3dui-ontology#>
  PREFIX owl: <http://www.w3.org/2002/07/owl#>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
- Return one rdflib.Graph.update-compatible SPARQL UPDATE request.
- Use one INSERT DATA block containing all supported triples.
- The INSERT DATA block must begin immediately after the prefix declarations.
- If no grounded update is supported, return an empty update:
  INSERT DATA { }

Required Output Shape
```sparql
PREFIX ex: <http://example.org/3dui-ontology#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

INSERT DATA {
}
```

Silent checks only:
- The SPARQL contains no banned placeholder tokens.
- Every non-empty update includes at least one exact URI from "communities".
- Every new owl:Class includes an rdfs:subClassOf parent.
- Every new class label, comment, URI, and edge is grounded in the input
  evidence.
After the closing fence, stop.
