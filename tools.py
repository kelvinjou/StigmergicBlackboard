from rdflib import Graph, RDFS


def query_subclass(parent_class_name):
    """
    Queries the immediate subclasses of a TTL/RDF class using rdflib.

    This tool finds classes where the given parent_class appears as the object of
    an rdfs:subClassOf triple.

    Example rdflib usage before returning:
        parent_uri = resolve_ttl_identifier(parent_class)
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
    g.parse("enhanced_xr.ttl", format="ttl")

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

    
    