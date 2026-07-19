Return only valid JSON.

Compare an ontology concept description (fact 1), with a source claim (fact 2).
Extract the relationship as a subject-predicate-object statement plus a brief reason.

Schema:
{
  "subject": "brief noun phrase from fact 1 or fact 2",
  "predicate": "supports|contradicts|requires|causes|is unrelated to",
  "object": "brief noun phrase from fact 1 or fact 2",
  "reason": "brief final reason"
}

Do not include markdown, analysis, chain-of-thought, or extra text.
