from rdflib import Graph, Literal, URIRef, RDFS


TTL_PATH = "enhanced_xr.ttl"

class Tools:

    def __init__(self):
        self.g = Graph()
        self.g.parse(TTL_PATH, format="ttl")


    def _local_name(self, uri) -> str:
        uri_str = str(uri)
        return uri_str.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


    def _format_value(self, value):
        if isinstance(value, URIRef):
            return {
                "uri": str(value),
                "name": self._local_name(value),
            }

        if isinstance(value, Literal):
            return {
                "value": str(value),
                "language": value.language,
                "datatype": str(value.datatype) if value.datatype else None,
            }

        return {"value": str(value)}


    def _resolve_ttl_identifier(self, class_name: str) -> URIRef:
        """Resolve a local TTL name like 'Concept' to its full URIRef."""
        if class_name.startswith("http://") or class_name.startswith("https://"):
            return URIRef(class_name)

        for _, namespace in self.g.namespaces():
            candidate = URIRef(str(namespace) + class_name)
            if (candidate, None, None) in self.g or (None, None, candidate) in self.g:
                return candidate

        for subject in set(self.g.subjects()):
            if self._local_name(subject).lower() == class_name.lower():
                return subject

        for obj in set(self.g.objects()):
            if isinstance(obj, URIRef) and self._local_name(obj).lower() == class_name.lower():
                return obj

        default_namespace = dict(self.g.namespaces()).get("")
        if default_namespace is None:
            raise ValueError(f"Could not resolve class name: {class_name}")

        return URIRef(str(default_namespace) + class_name)


    def query_subclass(self, parent_class_name: str):
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

        subclasses = []

        # subject_objects returns (subclass, parent_class)
        for subj, obj in self.g.subject_objects(predicate=RDFS.subClassOf):
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

    def inspect_class(self, target_class_name: str):
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

        target_uri = self._resolve_ttl_identifier(target_class_name)

        results = self.g.query(
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
                "predicate_name": self._local_name(row.predicate),
                "object": self._format_value(row.object),
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

    def recurse_n_layers(self, root_class: str, depth: int = 3):
        """
        Traverses subclass links up to a bounded depth from a root TTL/RDF class.

        This convenience tool is useful when the immediate children of a class are
        too broad, but a relevant concept may appear a few subclass levels below.
        It follows rdfs:subClassOf edges outward from root_class and returns every
        descendant class found from one through depth hops away.

        Args:
            root_class (str): The local TTL class identifier to start from, such
                as "Concept", "Task", or "HardwareComponent".
            depth (int): The maximum number of rdfs:subClassOf levels to traverse.
                Defaults to 3.

        Returns:
            list[str]: Local class names for all descendant classes found within
                the requested depth.
        """
        target_uri = self._resolve_ttl_identifier(root_class)
        visited = set()
        frontier = {target_uri}

        for _ in range(depth):
            next_frontier = set()

            for parent_uri in frontier:
                for subclass_uri in self.g.subjects(RDFS.subClassOf, parent_uri):
                    if subclass_uri in visited:
                        continue

                    visited.add(subclass_uri)
                    next_frontier.add(subclass_uri)

            frontier = next_frontier
            if not frontier:
                break

        return [self._local_name(uri) for uri in visited]

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
