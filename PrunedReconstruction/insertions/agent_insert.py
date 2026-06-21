import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

from dotenv import load_dotenv
from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS, URIRef


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL, LLM_TEMPERATURE, LLM_TOP_P
from LLMCompletionWrappers import client as llm_client

DEFAULT_MODEL = LLM_MODEL


def _extract_action(message: str):
    action_match = re.search(r"(?m)^Action:\s*(.+?)\s*$", message)
    input_match = re.search(
        r"(?ms)^Action Input:\s*(.+?)(?=\n(?:PAUSE|Thought:|Action:|Final Answer:|Answer:)|\Z)",
        message,
    )

    action = action_match.group(1).strip() if action_match else None
    action_input = input_match.group(1).strip() if input_match else None
    return action, action_input


def _extract_answer(message: str):
    answer_match = re.search(
        r"(?ms)^(?:Final Answer|Answer):\s*(.+?)(?=\n(?:Thought|Action|Action Input):|\Z)",
        message,
    )
    return answer_match.group(1).strip() if answer_match else None


def _strip_md_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_action_input(action_input: str):
    if action_input is None:
        return None

    action_input = _strip_md_fence(action_input)
    if not action_input:
        return ""

    try:
        return json.loads(action_input)
    except json.JSONDecodeError:
        return action_input.strip("\"'")

# trim outputs before feeding it back to the agent
def _compact_observation(result):
    if not isinstance(result, dict):
        if isinstance(result, list):
            return result[:40]
        return result

    compact = {}
    for key, value in result.items():
        if key in {"target_uri", "ttl_path", "properties"}:
            continue
        if key == "children" and isinstance(value, list):
            compact[key] = value[:40]
            if len(value) > 40:
                compact["children_truncated"] = len(value) - 40
            continue
        if key == "inserted" and isinstance(value, list):
            compact[key] = [
                {
                    "class_name": item.get("class_name"),
                    "parent_class_name": item.get("parent_class_name"),
                    "path": item.get("path"),
                }
                for item in value
                if isinstance(item, dict)
            ]
            continue
        if key == "skipped" and isinstance(value, list):
            compact[key] = [
                {
                    "class_name": item.get("class_name"),
                    "reason": item.get("reason"),
                    "path": item.get("path"),
                }
                for item in value
                if isinstance(item, dict)
            ]
            continue
        compact[key] = value
    return compact


class AgentInsertionTools:
    """Traversal and insertion tools over a pruned TTL ontology."""

    def __init__(
        self,
        ttl_path,
        summary="",
        generated_by=None,
        generation_mode="TRAVERSAL",
        max_traversal_calls=3,
    ):
        self.ttl_path = Path(ttl_path)
        self.summary = summary
        self.generated_by = generated_by
        self.generation_mode = generation_mode
        self.max_traversal_calls = max_traversal_calls
        self.g = Graph()
        self.g.parse(self.ttl_path, format="ttl")
        self.default_namespace = self._default_namespace()
        self.ontology = Namespace(str(self.default_namespace))
        self.traversal_calls = 0
        self.queried_parents = set()
        self.observed_classes = set()
        self.accepted_plan = None
        self.last_plan_result = None
        self.plan_submissions = 0
        self.observations = []
        self.last_insertion_result = None
        self.expected_relation_predicates = self._relation_predicates_in_summary()
        self.exact_class_literals = self._extract_exact_class_literals()

    def _default_namespace(self):
        default_namespace = dict(self.g.namespaces()).get("")
        if default_namespace is None:
            raise ValueError("TTL file must define a default namespace.")
        return default_namespace

    def _local_name(self, uri) -> str:
        uri_str = str(uri)
        return uri_str.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

    def _compact_uri(self, uri) -> str:
        uri_str = str(uri)
        namespace = str(self.default_namespace)
        if uri_str.startswith(namespace):
            return f":{uri_str.removeprefix(namespace)}"
        return f"<{uri_str}>"

    def _escape_turtle_literal(self, value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )

    def _normalize_local_name(self, value: str) -> str:
        value = str(value).strip()
        if value.startswith(":"):
            value = value[1:]
        if not value:
            raise ValueError("Class or property name cannot be empty.")
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", value):
            raise ValueError(f"Unsupported TTL local name: {value}")
        return value

    def _resolve_ttl_identifier(self, identifier: str) -> URIRef:
        identifier = self._normalize_local_name(identifier)

        for _, namespace in self.g.namespaces():
            candidate = URIRef(str(namespace) + identifier)
            if (
                (candidate, None, None) in self.g
                or (None, candidate, None) in self.g
                or (None, None, candidate) in self.g
            ):
                return candidate

        for uri in set(self.g.subjects()) | {
            obj for obj in self.g.objects() if isinstance(obj, URIRef)
        } | set(self.g.predicates()):
            if self._local_name(uri).lower() == identifier.lower():
                return uri

        return URIRef(str(self.default_namespace) + identifier)

    def _identifier_exists(self, identifier: str) -> bool:
        uri = self._resolve_ttl_identifier(identifier)
        return (
            (uri, None, None) in self.g
            or (None, uri, None) in self.g
            or (None, None, uri) in self.g
        )

    def _resource_kind(self, uri: URIRef) -> str:
        if (uri, RDF.type, OWL.ObjectProperty) in self.g:
            return "object_property"
        if (uri, RDF.type, OWL.DatatypeProperty) in self.g:
            return "datatype_property"
        if (uri, RDF.type, OWL.Class) in self.g:
            return "class"
        return "resource"

    def _relation_predicates_in_summary(self):
        summary_lower = self.summary.lower()
        ignored = {
            str(RDF.type),
            str(RDFS.label),
            str(RDFS.comment),
            str(RDFS.subClassOf),
        }
        return sorted(
            self._local_name(predicate)
            for predicate in set(self.g.predicates())
            if isinstance(predicate, URIRef)
            and str(predicate) not in ignored
            and self._local_name(predicate).lower() in summary_lower
        )

    def _extract_exact_class_literals(self):
        """Extract exact labels/comments from Turtle fragments in the summary."""
        hints = {}
        class_blocks = re.finditer(
            r"(?ms):(?P<name>[A-Za-z0-9_-]+)\s+"
            r"(?:rdf:type|a)\s+owl:Class\s*;(?P<body>.*?)(?:\n\s*\.\s*|\Z)",
            self.summary,
        )
        for match in class_blocks:
            body = match.group("body")
            values = {}
            for field, predicate in (
                ("label", "rdfs:label"),
                ("comment", "rdfs:comment"),
            ):
                literal_match = re.search(
                    rf'{re.escape(predicate)}\s+"((?:[^"\\]|\\.)*)"(?:@[A-Za-z-]+)?',
                    body,
                    flags=re.DOTALL,
                )
                if literal_match:
                    values[field] = bytes(
                        literal_match.group(1), "utf-8"
                    ).decode("unicode_escape")
            if values:
                hints[match.group("name")] = values
        return hints

    def grounding_catalog(self):
        """Return compact ontology identifiers relevant to the supplied summary."""
        summary_lower = self.summary.lower()
        identifiers = {}
        for uri in (
            set(self.g.subjects())
            | {obj for obj in self.g.objects() if isinstance(obj, URIRef)}
            | set(self.g.predicates())
        ):
            if not isinstance(uri, URIRef):
                continue
            name = self._local_name(uri)
            if name.lower() in summary_lower:
                identifiers[name] = self._resource_kind(uri)

        properties = []
        for uri in set(self.g.subjects(RDF.type, OWL.ObjectProperty)):
            properties.append(self._local_name(uri))

        return {
            "mentioned_existing_identifiers": dict(sorted(identifiers.items())),
            "object_properties": sorted(set(properties)),
            "relation_predicates_in_summary": self.expected_relation_predicates,
            "exact_class_literals": self.exact_class_literals,
        }

    def _record_traversal_call(self):
        if self.traversal_calls >= self.max_traversal_calls:
            raise ValueError(
                f"Traversal call budget exhausted ({self.max_traversal_calls}). "
                "Submit a reconstruction plan or abstain."
            )
        self.traversal_calls += 1

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

    def query_subclass(self, parent_class_name: str):
        self._record_traversal_call()
        parent_uri = self._resolve_ttl_identifier(parent_class_name)
        children = [
            self._local_name(subclass_uri)
            for subclass_uri in self.g.subjects(RDFS.subClassOf, parent_uri)
            if isinstance(subclass_uri, URIRef)
        ]
        children = sorted(set(children))
        normalized_parent = self._local_name(parent_uri)
        self.queried_parents.add(normalized_parent)
        self.observed_classes.add(normalized_parent)
        self.observed_classes.update(children)
        result = {
            "parent_class_name": normalized_parent,
            "children": children,
            "count": len(children),
            "traversal_calls_used": self.traversal_calls,
            "traversal_calls_remaining": (
                self.max_traversal_calls - self.traversal_calls
            ),
        }
        self.observations.append(
            {
                "tool": "query_subclass",
                "result": result,
            }
        )
        return result

    def inspect_class(self, target_class_name: str):
        self._record_traversal_call()
        target_uri = self._resolve_ttl_identifier(target_class_name)
        if (target_uri, None, None) not in self.g and (None, None, target_uri) not in self.g:
            result = {
                "target_class_name": target_class_name,
                "found": False,
                "count": 0,
                "traversal_calls_used": self.traversal_calls,
                "traversal_calls_remaining": (
                    self.max_traversal_calls - self.traversal_calls
                ),
            }
            self.observations.append(
                {
                    "tool": "inspect_class",
                    "result": result,
                }
            )
            return result

        normalized_target = self._local_name(target_uri)
        self.observed_classes.add(normalized_target)
        properties = [
            {
                "predicate": str(predicate),
                "predicate_name": self._local_name(predicate),
                "object": self._format_value(obj),
            }
            for predicate, obj in self.g.predicate_objects(target_uri)
        ]
        incoming_relations = [
            {
                "subject": self._local_name(subject),
                "predicate": self._local_name(predicate),
            }
            for subject, predicate in self.g.subject_predicates(target_uri)
            if isinstance(subject, URIRef)
            and predicate not in {RDF.type, RDFS.subClassOf}
        ]
        outgoing_relations = [
            {
                "predicate": item["predicate_name"],
                "object": item["object"].get("name"),
            }
            for item in properties
            if item["predicate"] not in {
                str(RDF.type),
                str(RDFS.label),
                str(RDFS.comment),
                str(RDFS.subClassOf),
            }
            and item["object"].get("name")
        ]

        result = {
            "target_class_name": normalized_target,
            "found": True,
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
                if item["predicate"] == str(RDFS.subClassOf) and "name" in item["object"]
            ],
            "incoming_relations": incoming_relations[:20],
            "outgoing_relations": outgoing_relations[:20],
            "count": len(properties),
            "traversal_calls_used": self.traversal_calls,
            "traversal_calls_remaining": (
                self.max_traversal_calls - self.traversal_calls
            ),
        }
        self.observations.append(
            {
                "tool": "inspect_class",
                "result": result,
            }
        )
        return result

    def _normalize_classes(self, classes):
        if isinstance(classes, dict):
            classes = classes.get("classes", [])
        if not isinstance(classes, list) or not classes:
            raise ValueError("classes must be a non-empty list.")

        normalized = []
        for item in classes:
            if not isinstance(item, dict):
                raise ValueError("Each class entry must be a JSON object.")
            class_name = self._normalize_local_name(item["class_name"])
            parent_name = self._normalize_local_name(item["parent_class_name"])
            exact_literals = self.exact_class_literals.get(class_name, {})
            normalized.append(
                {
                    "class_name": class_name,
                    "parent_class_name": parent_name,
                    "label": str(
                        exact_literals.get("label")
                        or item.get("label")
                        or class_name
                    ),
                    "comment": str(
                        exact_literals.get("comment")
                        or item.get("comment")
                        or ""
                    ).strip(),
                }
            )
        return normalized

    def _normalize_triples(self, triples, classes):
        if triples is None:
            triples = []
        if not isinstance(triples, list):
            raise ValueError("triples must be a list.")

        # Backward compatibility for older plans that nested outgoing relations
        # under class entries.
        combined = list(triples)
        for item in classes if isinstance(classes, list) else []:
            for relation in item.get("relations") or []:
                combined.append(
                    {
                        "subject": item.get("class_name"),
                        "predicate": relation.get("predicate"),
                        "object": relation.get("object"),
                    }
                )

        normalized = []
        seen = set()
        for item in combined:
            if not isinstance(item, dict):
                raise ValueError("Each triple must be a JSON object.")
            triple = {
                "subject": self._normalize_local_name(item["subject"]),
                "predicate": self._normalize_local_name(item["predicate"]),
                "object": self._normalize_local_name(item["object"]),
            }
            key = tuple(triple.values())
            if key not in seen:
                normalized.append(triple)
                seen.add(key)
        return normalized

    def _has_parent_cycle(self, parent_by_class):
        for class_name in parent_by_class:
            visited = set()
            current = class_name
            while current in parent_by_class:
                if current in visited:
                    return True
                visited.add(current)
                current = parent_by_class[current]
        return False

    def submit_reconstruction_plan(
        self,
        root_class,
        verified_parent,
        classes,
        triples=None,
        unresolved=None,
    ):
        """Validate and store one reconstruction plan before any graph mutation."""
        self.plan_submissions += 1
        errors = []
        warnings = []

        try:
            normalized_root = self._normalize_local_name(root_class)
            normalized_parent = self._normalize_local_name(verified_parent)
            normalized_classes = self._normalize_classes(classes)
            normalized_triples = self._normalize_triples(triples, classes)
        except (KeyError, TypeError, ValueError) as exc:
            result = {
                "accepted": False,
                "errors": [str(exc)],
                "warnings": [],
                "plan_submissions": self.plan_submissions,
            }
            self.last_plan_result = result
            self.accepted_plan = None
            return result

        class_names = [item["class_name"] for item in normalized_classes]
        class_name_set = set(class_names)
        if len(class_names) != len(class_name_set):
            errors.append("Plan contains duplicate class names.")

        root_entries = [
            item
            for item in normalized_classes
            if item["class_name"] == normalized_root
        ]
        if len(root_entries) != 1:
            errors.append("root_class must appear exactly once in classes.")
        elif root_entries[0]["parent_class_name"] != normalized_parent:
            errors.append(
                "verified_parent must match the root class parent_class_name."
            )

        if normalized_parent in class_name_set:
            errors.append("verified_parent must already exist outside the plan.")
        elif not self._identifier_exists(normalized_parent):
            errors.append(
                f"Verified parent '{normalized_parent}' does not exist."
            )

        parent_by_class = {
            item["class_name"]: item["parent_class_name"]
            for item in normalized_classes
        }
        for item in normalized_classes:
            class_name = item["class_name"]
            parent_name = item["parent_class_name"]
            if self._identifier_exists(class_name):
                errors.append(
                    f"Class '{class_name}' already exists in the pruned ontology."
                )
            if (
                parent_name not in class_name_set
                and not self._identifier_exists(parent_name)
            ):
                errors.append(
                    f"Parent '{parent_name}' for '{class_name}' does not exist "
                    "and is not included in the plan."
                )

        forbidden_predicates = {"label", "comment"}
        for triple in normalized_triples:
            subject = triple["subject"]
            predicate = triple["predicate"]
            object_name = triple["object"]
            if (
                subject not in class_name_set
                and not self._identifier_exists(subject)
            ):
                errors.append(
                    f"Triple subject '{subject}' does not exist and is not "
                    "included in the plan."
                )
            if predicate in forbidden_predicates:
                errors.append(
                    f"Literal predicate '{predicate}' belongs in a class "
                    "entry, not URI-to-URI triples."
                )
            elif not self._identifier_exists(predicate):
                errors.append(f"Triple predicate '{predicate}' does not exist.")
            if (
                object_name not in class_name_set
                and not self._identifier_exists(object_name)
            ):
                errors.append(
                    f"Triple object '{object_name}' does not exist and is not "
                    "included in the plan."
                )

        if self._has_parent_cycle(parent_by_class):
            errors.append("Plan contains a subclass cycle.")

        catalog_identifiers = self.grounding_catalog()[
            "mentioned_existing_identifiers"
        ]
        root_parent_grounded = (
            normalized_parent in self.observed_classes
            or normalized_parent in catalog_identifiers
        )
        if self.traversal_calls and not root_parent_grounded:
            warnings.append(
                "The verified root parent was not observed during traversal."
            )

        normalized_unresolved = [
            str(item).strip()
            for item in (unresolved or [])
            if str(item).strip()
        ]
        triple_predicates = {
            triple["predicate"] for triple in normalized_triples
        }
        unresolved_text = " ".join(normalized_unresolved).lower()
        for predicate in self.expected_relation_predicates:
            if (
                predicate not in triple_predicates
                and predicate.lower() not in unresolved_text
            ):
                errors.append(
                    f"Summary mentions relation '{predicate}', but the plan "
                    "contains no such triple and does not mark it unresolved."
                )

        plan = {
            "root_class": normalized_root,
            "verified_parent": normalized_parent,
            "classes": normalized_classes,
            "triples": normalized_triples,
            "unresolved": normalized_unresolved,
        }
        accepted = not errors
        self.accepted_plan = plan if accepted else None
        result = {
            "accepted": accepted,
            "errors": errors,
            "warnings": warnings,
            "root_parent_grounded": root_parent_grounded,
            "class_count": len(normalized_classes),
            "relation_count": len(normalized_triples),
            "unresolved_count": len(normalized_unresolved),
            "plan_submissions": self.plan_submissions,
        }
        self.last_plan_result = result
        return result

    def planning_state(self):
        return {
            "traversal_calls_used": self.traversal_calls,
            "traversal_calls_remaining": (
                self.max_traversal_calls - self.traversal_calls
            ),
            "queried_parents": sorted(self.queried_parents),
            "observed_classes": sorted(self.observed_classes),
            "plan_submissions": self.plan_submissions,
            "plan_accepted": bool(self.accepted_plan),
            "last_plan_result": self.last_plan_result,
            "observations": self.observations,
        }

    def plan_artifact(self):
        return {
            "plan": self.accepted_plan,
            "validation": self.last_plan_result,
            "state": self.planning_state(),
        }

    def plan_metrics(self):
        validation = self.last_plan_result or {}
        insertion = self.last_insertion_result or {}
        return {
            "plan_submissions": self.plan_submissions,
            "plan_accepted": bool(self.accepted_plan),
            "plan_validation_error_count": len(
                validation.get("errors") or []
            ),
            "plan_warning_count": len(
                validation.get("warnings") or []
            ),
            "root_parent_grounded": validation.get(
                "root_parent_grounded", False
            ),
            "unresolved_count": validation.get("unresolved_count", 0),
            "traversal_calls": self.traversal_calls,
            "planned_triple_count": validation.get("relation_count", 0),
            "inserted_triple_count": insertion.get(
                "inserted_triple_count", 0
            ),
            "grounding_catalog_size": len(
                self.grounding_catalog()["mentioned_existing_identifiers"]
            ),
        }

    def insert_class_batch(self, classes=None, triples=None):
        """
        Commit the accepted reconstruction plan to the current TTL file.

        Args:
            classes: Optional copy of the accepted classes. If provided, it must
                exactly match the accepted plan.
        """
        if not self.accepted_plan:
            raise ValueError(
                "No accepted reconstruction plan. Call "
                "submit_reconstruction_plan first."
            )

        normalized = self.accepted_plan["classes"]
        if classes is not None:
            supplied = self._normalize_classes(classes)
            if supplied != normalized:
                raise ValueError(
                    "Insertion classes differ from the accepted plan."
                )
        if triples is not None:
            supplied_triples = self._normalize_triples(triples, classes or [])
            if supplied_triples != self.accepted_plan["triples"]:
                raise ValueError(
                    "Insertion triples differ from the accepted plan."
                )

        item_by_name = {item["class_name"]: item for item in normalized}
        ordered = []
        remaining = set(item_by_name)
        while remaining:
            ready = sorted(
                class_name
                for class_name in remaining
                if item_by_name[class_name]["parent_class_name"] not in remaining
            )
            if not ready:
                raise ValueError("Accepted plan contains an insertion-order cycle.")
            for class_name in ready:
                ordered.append(item_by_name[class_name])
                remaining.remove(class_name)

        normalized = ordered
        new_class_names = {item["class_name"] for item in normalized}
        inserted = []
        skipped = []
        ttl_entries = []

        for item in normalized:
            class_uri = URIRef(str(self.default_namespace) + item["class_name"])
            parent_uri = self._resolve_ttl_identifier(item["parent_class_name"])
            parent_exists = (parent_uri, None, None) in self.g or item["parent_class_name"] in new_class_names
            if not parent_exists:
                raise ValueError(
                    f"Parent class '{item['parent_class_name']}' does not exist in the pruned ontology "
                    "or in this insertion batch."
                )

            if (class_uri, None, None) in self.g:
                skipped.append(
                    {
                        "class_name": item["class_name"],
                        "reason": "already_exists",
                        "path": self._class_path(class_uri),
                    }
                )
                continue

            self.g.add((class_uri, RDF.type, OWL.Class))
            self.g.add((class_uri, RDFS.label, Literal(item["label"], lang="en")))
            self.g.add((class_uri, RDFS.subClassOf, parent_uri))
            if item["comment"]:
                self.g.add((class_uri, RDFS.comment, Literal(item["comment"], lang="en")))

            lines = [
                f":{item['class_name']} a owl:Class ;",
                f"    rdfs:label \"{self._escape_turtle_literal(item['label'])}\"@en ;",
            ]
            if item["comment"]:
                lines.append(
                    f"    rdfs:comment "
                    f"\"{self._escape_turtle_literal(item['comment'])}\"@en ;"
                )
            lines.append(f"    rdfs:subClassOf {self._compact_uri(parent_uri)} .")
            ttl_entries.append("\n".join(lines))

            inserted.append(
                {
                    "class_name": item["class_name"],
                    "parent_class_name": item["parent_class_name"],
                    "path": self._class_path(class_uri),
                }
            )

        inserted_triples = []
        triple_entries = []
        for triple in self.accepted_plan["triples"]:
            subject_uri = self._resolve_ttl_identifier(triple["subject"])
            predicate_uri = self._resolve_ttl_identifier(triple["predicate"])
            object_uri = self._resolve_ttl_identifier(triple["object"])
            statement = (subject_uri, predicate_uri, object_uri)
            if statement in self.g:
                continue
            self.g.add(statement)
            inserted_triples.append(triple)
            triple_entries.append(
                f"{self._compact_uri(subject_uri)} "
                f"{self._compact_uri(predicate_uri)} "
                f"{self._compact_uri(object_uri)} ."
            )

        ttl_entries.extend(triple_entries)
        if ttl_entries:
            generated_at = datetime.now(timezone.utc).isoformat()
            generated_by = self.generated_by or "unknown"
            self._append_ttl_block(
                "\n\n"
                "############################################\n"
                f"# AGENT GENERATION ({self.generation_mode}) OUTPUT\n"
                f"# Generated at: {generated_at}\n"
                f"# Generated by: {generated_by}\n"
                "############################################\n\n"
                + "\n\n".join(ttl_entries)
                + "\n"
            )
            self._verify_ttl_file()

        result = {
            "ttl_path": str(self.ttl_path),
            "inserted": inserted,
            "skipped": skipped,
            "inserted_count": len(inserted),
            "inserted_triple_count": len(inserted_triples),
            "skipped_count": len(skipped),
        }
        self.last_insertion_result = result
        return result


class AgentInsert:
    def __init__(
        self,
        modified_ttl_path,
        summary_file_path,
        model=DEFAULT_MODEL,
        allow_traversal=True,
        temperature=LLM_TEMPERATURE,
        top_p=LLM_TOP_P,
    ):
        load_dotenv()
        self.client = llm_client
        self.modified_ttl_path = Path(modified_ttl_path)
        self.summary_file_path = Path(summary_file_path)
        self.summary = self.summary_file_path.read_text(encoding="utf-8")
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.allow_traversal = allow_traversal
        generation_mode = (
            "TRAVERSAL + INSERTION TOOLS"
            if allow_traversal
            else "INSERTION TOOL ONLY"
        )
        self.tools = AgentInsertionTools(
            self.modified_ttl_path,
            summary=self.summary,
            generated_by=model,
            generation_mode=generation_mode,
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.model_calls = 0
        self.messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            }
        ]

    def _system_prompt(self):
        if self.allow_traversal:
            access_instructions = """
            A compact grounding catalog is supplied below. It is generated
            deterministically from the current pruned ontology and should be
            enough for the first plan.

            Fallback tools available only when validation reports missing
            grounding:
            - query_subclass(parent_class_name): returns direct subclasses.
            - inspect_class(target_class_name): returns class metadata and
              boundary relations.

            Do not traverse before the first plan. Use at most three fallback
            calls after a rejected plan.
            """
            action_names = (
                "submit_reconstruction_plan, query_subclass, inspect_class"
            )
            grounding_catalog = self.tools.grounding_catalog()
        else:
            access_instructions = """
            Traversal and inspection tools are unavailable in this experiment.
            Infer the root placement from the summary alone. Do not request a
            traversal tool.
            """
            action_names = "submit_reconstruction_plan"
            grounding_catalog = {
                "available": False,
                "reason": "disabled for no-traversal ablation",
            }

        return dedent(
            f"""
            You are an ontology reconstruction insertion agent.

            Root class name: Concept

            You are given a textual summary of an ontology community that was
            pruned from a TTL ontology. Reconstruct only that missing community.

            Summary of pruned community:
            {self.summary}

            {access_instructions}

            Compact grounding catalog:
            {json.dumps(grounding_catalog, ensure_ascii=False)}

            Planning and insertion tools available in both experiments:
            - submit_reconstruction_plan(root_class, verified_parent, classes,
              triples, unresolved): validates and stores a proposed
              reconstruction.
            - insert_class_batch(): is committed automatically after acceptance.

            Required workflow:
            1. Determine the missing root and its existing parent.
            2. Immediately submit one complete plan. If validation rejects it, correct
               only the reported errors and resubmit.
            3. Include every grounded relationship stated by the summary,
               including relationships whose subject is an existing class.
            4. The runtime commits accepted plans automatically.

            Plan JSON shape:
            {{
              "root_class": "...",
              "verified_parent": "...",
              "classes": [
                {{
                  "class_name": "...",
                  "parent_class_name": "...",
                  "label": "...",
                  "comment": "..."
                }}
              ],
              "triples": [
                {{
                  "subject": "existing-or-new-resource",
                  "predicate": "existing-object-property",
                  "object": "existing-or-new-resource"
                }}
              ],
              "unresolved": []
            }}

            Reconstruction rules:
            - Prefer exact class names and descriptions from the summary.
            - Copy quoted labels and comments exactly. Do not paraphrase them.
            - Extract all relation rows and lists, not just representative
              examples. High recall is required.
            - Put the primary owl:Class type, label, comment, and parent in the
              class entry. Supplemental rdf:type or rdfs:subClassOf statements
              may appear in triples.
            - Put every other URI-to-URI statement in triples. The subject may
              be an existing resource, which is essential for inverse boundary
              relations such as ExistingTechnique supportsTask NewTask.
            - Use one tool call per assistant response.
            - Include a triple only when its predicate is in the catalog and
              both endpoints exist or are included in the same plan.
            - Put uncertain facts in unresolved instead of inventing triples.
            - If the root parent cannot be determined, return:
              Final Answer: INSUFFICIENT_EVIDENCE
            - Never output Turtle syntax.

            Tool call format:
            Thought: concise reason for next lookup
            Action: one of {action_names}
            Action Input: local class name or JSON object
            PAUSE

            Final response format:
            Final Answer: concise result
            """
        ).strip()

    def send_messages(self, message):
        messages = [self.messages[0]]
        messages.append(
            {
                "role": "user",
                "content": (
                    "Structured reconstruction state:\n"
                    + json.dumps(
                        self.tools.planning_state(),
                        ensure_ascii=False,
                    )
                ),
            }
        )
        messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            top_p=self.top_p,
        )
        self.model_calls += 1
        content = response.choices[0].message.content
        self.messages = messages + [{"role": "assistant", "content": content}]
        if response.usage:
            self.prompt_tokens += response.usage.prompt_tokens or 0
            self.completion_tokens += response.usage.completion_tokens or 0
            self.total_tokens += response.usage.total_tokens or 0
        return content

    # batch insert since once we find target community, everything else would be under that
    def run(self, max_turns=12, verbose=True):
        if self.allow_traversal:
            next_message = (
                "Submit the complete reconstruction plan now from the summary "
                "and compact grounding catalog. Do not traverse first."
            )
            known_tools = {
                "query_subclass": self.tools.query_subclass,
                "inspect_class": self.tools.inspect_class,
                "submit_reconstruction_plan": (
                    self.tools.submit_reconstruction_plan
                ),
                "insert_class_batch": self.tools.insert_class_batch,
            }
        else:
            next_message = (
                "Reconstruct the missing community from the summary and submit "
                "a complete reconstruction plan before insertion."
            )
            known_tools = {
                "submit_reconstruction_plan": (
                    self.tools.submit_reconstruction_plan
                ),
                "insert_class_batch": self.tools.insert_class_batch,
            }

        for _ in range(max_turns):
            response = self.send_messages(next_message)
            if verbose:
                print(response)
                print()

            action, action_input = _extract_action(response)
            answer = _extract_answer(response)
            if not action:
                if answer:
                    return answer
                return response
            if action not in known_tools:
                next_message = (
                    f"Observation: Unknown tool '{action}'. "
                    f"Available tools: {', '.join(known_tools)}"
                )
                continue

            tool_input = _parse_action_input(action_input)
            try:
                if isinstance(tool_input, dict):
                    result = known_tools[action](**tool_input)
                else:
                    result = known_tools[action](tool_input)
            except Exception as exc:
                result = {"error": str(exc), "tool": action}
            compact_result = _compact_observation(result)
            if action == "submit_reconstruction_plan":
                if compact_result.get("accepted"):
                    insertion = self.tools.insert_class_batch()
                    return (
                        f"Inserted {insertion['inserted_count']} classes and "
                        f"{insertion['inserted_triple_count']} grounded triples."
                    )
                else:
                    next_message = (
                        "The plan was rejected. Correct the reported validation "
                        "errors and resubmit the complete plan. Use a fallback "
                        "lookup only if the error cannot be resolved from the "
                        "catalog."
                    )
            elif action == "insert_class_batch":
                if compact_result.get("error"):
                    next_message = (
                        "Insertion failed. Use the reported error and structured "
                        "state to correct the plan."
                    )
                else:
                    next_message = (
                        "Insertion succeeded. Provide the concise Final Answer now."
                    )
            elif self.allow_traversal:
                next_message = (
                    "Continue from the structured state. Use another traversal "
                    "call only if needed; otherwise submit the complete plan."
                )
            else:
                next_message = (
                    "Submit the complete reconstruction plan from the summary."
                )

        return None
