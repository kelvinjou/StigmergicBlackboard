import re
from datetime import date
from textwrap import dedent

from rdflib import Graph, Literal, Namespace, URIRef, RDFS, RDF, OWL

TTL_PATH = "enhanced_xr.ttl"

class Tools:
    def __init__(self, ttl_path: str = TTL_PATH):
        self.ttl_path = ttl_path
        self.g = Graph()
        self.g.parse(self.ttl_path, format="ttl")
        self.default_namespace = self._default_namespace()
        self.ontology = Namespace(str(self.default_namespace))

    def _local_name(self, uri) -> str:
        uri_str = str(uri)
        return uri_str.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

    def _default_namespace(self):
        default_namespace = dict(self.g.namespaces()).get("")
        if default_namespace is None:
            raise ValueError("TTL file must define a default namespace.")
        return default_namespace

    def _compact_uri(self, uri) -> str:
        uri_str = str(uri)
        namespace = str(self.default_namespace)
        if uri_str.startswith(namespace):
            return f":{uri_str.removeprefix(namespace)}"
        return f"<{uri_str}>"

    def _escape_turtle_literal(self, value: str) -> str:
        return (
            value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )

    def _slugify(self, value: str, max_words: int = 8) -> str:
        words = re.findall(r"[A-Za-z0-9]+", value)
        if not words:
            return "Evidence"
        return "".join(word[:1].upper() + word[1:] for word in words[:max_words])

    def _unique_evidence_name(self, target_class_name: str, evidence: str) -> str:
        base_name = f"{target_class_name}Evidence{self._slugify(evidence, max_words=6)}"
        candidate_name = base_name
        index = 2

        while URIRef(str(self.default_namespace) + candidate_name) in self.g.subjects():
            candidate_name = f"{base_name}{index}"
            index += 1

        return candidate_name

    def _class_path(self, target_uri: URIRef):
        parent_lookup = {
            child: parent
            for child, parent in self.g.subject_objects(predicate=RDFS.subClassOf)
            if isinstance(child, URIRef) and isinstance(parent, URIRef)
        }

        path = [self._local_name(target_uri)]
        visited = {target_uri}
        current = target_uri

        while current in parent_lookup:
            parent = parent_lookup[current]
            if parent in visited:
                break

            path.append(self._local_name(parent))
            visited.add(parent)
            current = parent

        return list(reversed(path))

    def _append_ttl_block(self, block: str):
        with open(self.ttl_path, "a", encoding="utf-8") as ttl_file:
            ttl_file.write(block)

    def _verify_ttl_file(self):
        verify_graph = Graph()
        verify_graph.parse(self.ttl_path, format="ttl")

    def _ensure_grounded_evidence_schema(self):
        evidence_class = self.ontology.GroundedEvidence
        evidence_property = self.ontology.isGroundedEvidenceFor

        schema_block_parts = []

        if (evidence_class, None, None) not in self.g:
            self.g.add((evidence_class, RDF.type, OWL.Class))
            self.g.add((evidence_class, RDFS.label, Literal("Grounded Evidence", lang="en")))
            self.g.add((evidence_class, RDFS.subClassOf, self.ontology.Concept))
            self.g.add((
                evidence_class,
                RDFS.comment,
                Literal(
                    "A user-provided evidence class that records grounded quantitative or qualitative support for an ontology concept.",
                    lang="en",
                ),
            ))
            schema_block_parts.append(
                dedent("""
:GroundedEvidence rdf:type owl:Class ;
    rdfs:label "Grounded Evidence"@en ;
    rdfs:subClassOf :Concept ;
    rdfs:comment "A user-provided evidence class that records grounded quantitative or qualitative support for an ontology concept."@en .
""")
            )

        if (evidence_property, None, None) not in self.g:
            self.g.add((evidence_property, RDF.type, OWL.ObjectProperty))
            self.g.add((evidence_property, RDFS.label, Literal("is grounded evidence for", lang="en")))
            self.g.add((
                evidence_property,
                RDFS.comment,
                Literal("Links a grounded evidence class to the ontology concept it supports.", lang="en"),
            ))
            self.g.add((evidence_property, RDFS.domain, evidence_class))
            self.g.add((evidence_property, RDFS.range, self.ontology.Concept))
            schema_block_parts.append(
                dedent("""
:isGroundedEvidenceFor rdf:type owl:ObjectProperty ;
    rdfs:label "is grounded evidence for"@en ;
    rdfs:comment "Links a grounded evidence class to the ontology concept it supports."@en ;
    rdfs:domain :GroundedEvidence ;
    rdfs:range :Concept .
""")
            )

        if schema_block_parts:
            self._append_ttl_block(
                "\n###############################################################################\n"
                "# USER-GROUNDED EVIDENCE SCHEMA\n"
                "###############################################################################\n"
                + "".join(schema_block_parts)
            )

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