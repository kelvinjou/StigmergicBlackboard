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
- "ontology_config": namespace, root class, relationship property type,
  domain/range predicate style, and SPARQL prefixes for the selected ontology.
- "communities": existing ontology communities, each with "uri", "description",
  and "strength".
- "object_properties": optional declared ontology relationship predicates,
  keyed by URI, with labels, comments, domains, ranges, superproperties, and
  inverses when available. This field may be absent or empty.
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
  For example, an evidence phrase like "widgets", the label "Widget", and a
  community local name "Widget" refer to the same concept when they match after
  case, whitespace, hyphen, and trailing plural "s"/"es" normalization.
- When evidence names a singular/plural variant of an existing community,
  reuse the exact existing community URI. Do not create a new pluralized or
  singularized owl:Class.
- If both relationship endpoints are already represented by provided
  communities, insert a relationship edge between those exact existing
  community URIs. If "object_properties" is provided and contains a suitable
  predicate, reuse it; otherwise declare the chosen predicate as a
  {{RELATIONSHIP_PROPERTY_TYPE_QNAME}} in the same INSERT DATA block. Never add,
  change, or repeat an rdfs:subClassOf triple on a community that already
  exists; existing classes keep their current parent.
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
  brackets, exactly as given in the "communities" input (for example
  <{{ONTOLOGY_EXAMPLE_URI}}>).
- Before creating any new class, compare the evidence phrase against all
  provided community URIs, local names, labels, and descriptions. Normalize by
  lowercasing, removing punctuation/whitespace/hyphens, and comparing simple
  singular/plural variants. If a normalized match exists, use that existing URI.
- New concept names must come from actual evidence phrases, converted to
  PascalCase under the {{ONTOLOGY_PREFIX}}: namespace.
- New concept labels must be the human-readable evidence phrase, not a generic
  label.
- New concept comments must summarize the concrete evidence phrase in one short
  sentence.
- Every new owl:Class must include exactly one rdfs:subClassOf triple so it is
  not disconnected from the ontology class hierarchy. Give a new class a single
  parent; never list two parents that belong to unrelated top-level categories.
- Choose the rdfs:subClassOf parent by semantic fit: pick the single provided
  community that the new concept most specifically IS-A-KIND-OF, judging from
  that community's own uri, label, and description. Prefer the most specific
  fitting community over a broad one. If no provided community is a genuine
  parent, attach the new class to the most general/root concept class of the
  ontology rather than forcing an ill-fitting parent.
- Do not make a caused or affected concept a subclass of the concept that causes
  or produces it; connect them with the causal relationship edge instead.
- Relationship predicates must be {{RELATIONSHIP_PROPERTY_TYPE_QNAME}}
  predicates.
- If "object_properties" is present, prefer an existing predicate from it when
  its URI local name, label, comment, domain, or range fits the evidence
  relationship.
- When reusing a predicate from "object_properties", write its exact URI; use
  angle brackets for full URIs.
- If "object_properties" is absent, empty, or has no suitable predicate, create
  a new predicate from the evidence relationship.
- Any newly created predicate must be declared in the same `INSERT DATA` block
  as a
  {{RELATIONSHIP_PROPERTY_TYPE_QNAME}}, with an evidence-grounded `rdfs:label`
  and `rdfs:comment`; include {{PROPERTY_DOMAIN_PREDICATE_QNAME}} and
  {{PROPERTY_RANGE_PREDICATE_QNAME}} when the endpoints are clear.
- New predicate names must come from the evidence relationship and be converted
  to lowerCamelCase under the `{{ONTOLOGY_PREFIX}}:` namespace.

Class Hierarchy Integrity (disjointness)
- rdfs:subClassOf means "is a kind of", not "is related to". Only use it when the
  child genuinely IS a specialization of the parent.
- Ontologies typically partition their concepts into top-level categories that
  are mutually disjoint (for example, physical things vs. abstract methods vs.
  properties of people). Infer these categories from the provided communities'
  descriptions. A class may descend from only ONE such category; placing any
  class under two disjoint categories makes the ontology inconsistent and the
  update will be rejected.
- When the evidence describes an association BETWEEN concepts of different
  categories -- one enabling, supporting, using, requiring, or causing another --
  express it as a relationship edge, never with rdfs:subClassOf. An artifact is
  not "a kind of" the method it supports, and a method is not "a kind of" the
  artifact it uses.
- Example (abstract): if evidence says a concept in category A "supports" a
  concept in category B, emit
  <existing-A-uri> <declared-relationship-property-uri> <existing-B-uri>, and do NOT add
  rdfs:subClassOf <existing-B-uri> to the category-A concept.

Hard Bans
- Never output placeholder names or generic template text.
- Never output these tokens: NewCommunity, ExistingCommunity,
  ExistingCommunityA, ExistingCommunityB, inferredPredicate, New Concept,
  Short description inferred from evidence.
- Never invent relationships that are not supported by the evidence.
- Never place a class under two disjoint top-level categories, and never use
  rdfs:subClassOf to express a mere association between concepts of different
  categories (use a relationship edge instead).
- Never emit DELETE, DROP, CLEAR, LOAD, SERVICE, or any operation other than
  INSERT DATA.

SPARQL Requirements
- Include these prefixes once at the top of the SPARQL block:
  {{SPARQL_PREFIX_LINES_INDENTED}}
- Return one rdflib.Graph.update-compatible SPARQL UPDATE request.
- Use one INSERT DATA block containing all supported triples.
- The INSERT DATA block must begin immediately after the prefix declarations.
- If no grounded update is supported, return an empty update:
  INSERT DATA { }

Required Output Shape
```sparql
{{SPARQL_PREFIX_LINES}}

INSERT DATA {
}
```

Silent checks only:
- The SPARQL contains no banned placeholder tokens.
- Every non-empty update includes at least one exact URI from "communities".
- Every new owl:Class includes exactly one rdfs:subClassOf parent, and is not
  placed under two disjoint top-level categories.
- No rdfs:subClassOf is used where the relationship is a mere association between
  concepts of different categories.
- Every predicate used between two class/community resources is either listed in
  optional "object_properties" when that field is provided, or declared in this
  INSERT DATA block as {{RELATIONSHIP_PROPERTY_TYPE_QNAME}}.
- Every new class label, comment, URI, and edge is grounded in the input
  evidence.
After the closing fence, stop.
