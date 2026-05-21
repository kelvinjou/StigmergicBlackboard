from rdflib import Graph, Literal, URIRef, RDFS


TTL_PATH = "enhanced_xr.ttl"


def _local_name(uri) -> str:
    uri_str = str(uri)
    return uri_str.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _format_value(value):
    if isinstance(value, URIRef):
        return {
            "uri": str(value),
            "name": _local_name(value),
        }

    if isinstance(value, Literal):
        return {
            "value": str(value),
            "language": value.language,
            "datatype": str(value.datatype) if value.datatype else None,
        }

    return {"value": str(value)}


def _resolve_ttl_identifier(g: Graph, class_name: str) -> URIRef:
    """Resolve a local TTL name like 'Concept' to its full URIRef."""
    if class_name.startswith("http://") or class_name.startswith("https://"):
        return URIRef(class_name)

    for _, namespace in g.namespaces():
        candidate = URIRef(str(namespace) + class_name)
        if (candidate, None, None) in g or (None, None, candidate) in g:
            return candidate

    for subject in set(g.subjects()):
        if _local_name(subject).lower() == class_name.lower():
            return subject

    for obj in set(g.objects()):
        if isinstance(obj, URIRef) and _local_name(obj).lower() == class_name.lower():
            return obj

    default_namespace = dict(g.namespaces()).get("")
    if default_namespace is None:
        raise ValueError(f"Could not resolve class name: {class_name}")

    return URIRef(str(default_namespace) + class_name)


def query_subclass(parent_class_name: str):
    """
    Queries the immediate subclasses of a TTL/RDF class using rdflib.

    This tool finds classes where the given parent_class appears as the object of
    an rdfs:subClassOf triple.

    Example rdflib usage before returning:
        parent_uri = _resolve_ttl_identifier(parent_class)
        results = graph.query('''
            SELECT ?child WHERE {
                ?child rdfs:subClassOf ?parent .
            }
        ''',
            initBindings={"parent": parent_uri}
        )
        children = [str(row.child) for row in results]

    Args:
        parent_class_name (str): The TTL class identifier whose immediate rdfs:subClassOf
            children should be returned, provided as a prefixed name.

    Returns:
        dict: A structured subclass result containing:
            - parent_class_name: The queried parent class
            - children: Direct subclass identifiers found in the graph
            - count: The number of direct subclasses found
    """

    g = Graph()
    g.parse(TTL_PATH, format="ttl")

    subclasses = []

    # subject_objects returns (subclass, parent_class)
    for subj, obj in g.subject_objects(predicate=RDFS.subClassOf):
        # Check if the parent class URI ends with the name (handling both # and /)
        obj_str = str(obj)
        if obj_str.endswith(parent_class_name) or obj_str.rsplit('#', 1)[-1] == parent_class_name or obj_str.rsplit('/', 1)[-1] == parent_class_name:
            # Extract the local name of the subclass for a clean list
            subclass_name = str(subj).rsplit('#', 1)[-1].rsplit('/', 1)[-1]
            subclasses.append(subclass_name)

    return {
        "parent_class_name": parent_class_name,
        "children": subclasses,
        "count": len(subclasses)
    }

def get_class_info(target_class_name: str):
    """
    Queries descriptive RDF/RDFS metadata for a TTL/RDF class using rdflib.

    This tool finds triples where the given class appears as the subject, such as
    rdf:type, rdfs:label, rdfs:subClassOf, and rdfs:comment.

    Example rdflib usage before returning:
        target_uri = _resolve_ttl_identifier(graph, target_class_name)
        results = graph.query('''
            SELECT ?predicate ?object WHERE {
                ?target_class ?predicate ?object .
            }
        ''',
            initBindings={"target_class": target_uri}
        )
        properties = [
            {
                "predicate": str(row.predicate),
                "object": str(row.object)
            }
            for row in results
        ]

    Args:
        target_class_name (str): The TTL class identifier whose metadata should be
            returned, provided as a local class name such as "Education".

    Returns:
        dict: A structured class metadata result containing:
            - target_class_name: The queried class name
            - target_uri: The resolved URI for the class
            - label: rdfs:label values found for the class
            - comment: rdfs:comment values found for the class
            - subclass_of: Direct rdfs:subClassOf parent class names
            - properties: All predicate-object records for the class
            - count: The number of predicate-object records found
    """
    g = Graph()
    g.parse(TTL_PATH, format="ttl")
    target_uri = _resolve_ttl_identifier(g, target_class_name)

    results = g.query(
        """
        SELECT ?predicate ?object WHERE {
            ?target_class ?predicate ?object .
        }
        """,
        initBindings={"target_class": target_uri}
    )

    properties = [
        {
            "predicate": str(row.predicate),
            "predicate_name": _local_name(row.predicate),
            "object": _format_value(row.object),
        }
        for row in results
    ]

    return {
        "target_class_name": target_class_name,
        "target_uri": str(target_uri),
        "label": [
            item["object"]["value"]
            for item in properties
            if item["predicate"] == str(RDFS.label)
        ],
        "comment": [
            item["object"]["value"]
            for item in properties
            if item["predicate"] == str(RDFS.comment)
        ],
        "subclass_of": [
            item["object"]["name"]
            for item in properties
            if item["predicate"] == str(RDFS.subClassOf)
        ],
        "properties": properties,
        "count": len(properties),
    }

# def query_relations(target_class_name: str):
#     g = Graph()
#     g.parse(TTL_PATH, format="ttl")
#     target_uri = _resolve_ttl_identifier(g, target_class_name)

#     results = g.query(
#         """
#         SELECT ?subject ?predicate ?object WHERE {
#             {   
#                 ?target_class ?predicate ?object .
#                 BIND(?target_class AS ?subject)
#             }
#             UNION
#             {
#                 ?subject ?predicate ?target_class .
#                 BIND(?target_class AS ?object)
#             }
#         }
#         """,
#         initBindings={"target_class": target_uri}
#     )

#     triples = [
#         {
#             "subject": str(row.subject),
#             "subject_name": _local_name(row.subject),
#             "predicate": str(row.predicate),
#             "predicate_name": _local_name(row.predicate),
#             "object": str(row.object),
#             "object_name": _local_name(row.object),
#         }
#         for row in results
#     ]

#     as_subject = [
#         triple for triple in triples
#         if triple["subject"] == str(target_uri)
#     ]
#     as_object = [
#         triple for triple in triples
#         if triple["object"] == str(target_uri)
#     ]

#     return {
#         "target_class_name": target_class_name,
#         "target_uri": str(target_uri),
#         "as_subject": as_subject,
#         "as_object": as_object,
#         "triples": triples,
#         "count": len(triples),
#     }
