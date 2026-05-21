### Determine subchildren (relations) via rdflib (and its relations)
### ALWAYS start off with a pointer to the root node

### Query relations

query_relations:

Query triples where the given class appears in either the subject or the object.

Example rdflib usage before returning:
    target_uri = resolve_ttl_identifier(target_class)
    results = graph.query(
        """
        SELECT ?subject ?predicate ?object WHERE {
            {
                ?target_class ?predicate ?object .
                BIND(?target_class AS ?subject)
            }
            UNION
            {
                ?subject ?predicate ?target_class .
                BIND(?target_class AS ?object)
            }
        }
        """,
        initBindings={"target_class": target_uri}
    )
    triples = [
        {
            "subject": str(row.subject),
            "predicate": str(row.predicate),
            "object": str(row.object)
        }
        for row in results
    ]

Args:
    target_class (str): The target TTL class identifier to find in subject or object position.

Returns:
    dict: A structured triple lookup result containing:
        - target_class: The queried TTL class identifier
        - as_subject: Triples where the target class appears as the subject
        - as_object: Triples where the target class appears as the object
        - triples: All matching triples as subject-predicate-object records
        - count: The total number of matching triples found