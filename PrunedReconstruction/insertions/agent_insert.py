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

from config import LLM_MODEL
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

    def __init__(self, ttl_path, generated_by=None, generation_mode="TRAVERSAL"):
        self.ttl_path = Path(ttl_path)
        self.generated_by = generated_by
        self.generation_mode = generation_mode
        self.g = Graph()
        self.g.parse(self.ttl_path, format="ttl")
        self.default_namespace = self._default_namespace()
        self.ontology = Namespace(str(self.default_namespace))

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
            if (candidate, None, None) in self.g or (None, None, candidate) in self.g:
                return candidate

        for uri in set(self.g.subjects()) | {
            obj for obj in self.g.objects() if isinstance(obj, URIRef)
        }:
            if self._local_name(uri).lower() == identifier.lower():
                return uri

        return URIRef(str(self.default_namespace) + identifier)

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
        parent_uri = self._resolve_ttl_identifier(parent_class_name)
        children = [
            self._local_name(subclass_uri)
            for subclass_uri in self.g.subjects(RDFS.subClassOf, parent_uri)
            if isinstance(subclass_uri, URIRef)
        ]
        children = sorted(set(children))
        return {
            "parent_class_name": self._local_name(parent_uri),
            "children": children,
            "count": len(children),
        }

    def inspect_class(self, target_class_name: str):
        target_uri = self._resolve_ttl_identifier(target_class_name)
        if (target_uri, None, None) not in self.g and (None, None, target_uri) not in self.g:
            return {
                "target_class_name": target_class_name,
                "found": False,
                "count": 0,
            }

        properties = [
            {
                "predicate": str(predicate),
                "predicate_name": self._local_name(predicate),
                "object": self._format_value(obj),
            }
            for predicate, obj in self.g.predicate_objects(target_uri)
        ]

        return {
            "target_class_name": self._local_name(target_uri),
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
            "count": len(properties),
        }

    def insert_class_batch(self, classes):
        """
        Add one or more owl:Class nodes to the current TTL file.

        Args:
            classes: list of objects with class_name, parent_class_name, label,
                comment, and optional relations. Each relation is an object with
                predicate and object local names, for example:
                {"predicate": "coveredInChapter", "object": "Ch8"}.
        """
        if isinstance(classes, dict):
            classes = classes.get("classes", [])
        if not isinstance(classes, list) or not classes:
            raise ValueError("insert_class_batch expects a non-empty classes list.")

        normalized = []
        for item in classes:
            if not isinstance(item, dict):
                raise ValueError("Each class entry must be a JSON object.")
            class_name = self._normalize_local_name(item["class_name"])
            parent_name = self._normalize_local_name(item["parent_class_name"])
            normalized.append(
                {
                    "class_name": class_name,
                    "parent_class_name": parent_name,
                    "label": str(item.get("label") or class_name),
                    "comment": str(item.get("comment") or "").strip(),
                    "relations": item.get("relations") or [],
                }
            )

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

            relation_lines = []
            for relation in item["relations"]:
                if not isinstance(relation, dict):
                    continue
                predicate_uri = self._resolve_ttl_identifier(relation["predicate"])
                object_uri = self._resolve_ttl_identifier(relation["object"])
                self.g.add((class_uri, predicate_uri, object_uri))
                relation_lines.append(
                    f"    {self._compact_uri(predicate_uri)} {self._compact_uri(object_uri)} ;"
                )

            lines = [
                f":{item['class_name']} a owl:Class ;",
                f"    rdfs:label \"{self._escape_turtle_literal(item['label'])}\"@en ;",
            ]
            lines.extend(relation_lines)
            lines.append(f"    rdfs:comment \"{self._escape_turtle_literal(item['comment'])}\"@en ;")
            lines.append(f"    rdfs:subClassOf {self._compact_uri(parent_uri)} .")
            ttl_entries.append("\n".join(lines))

            inserted.append(
                {
                    "class_name": item["class_name"],
                    "parent_class_name": item["parent_class_name"],
                    "path": self._class_path(class_uri),
                }
            )

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

        return {
            "ttl_path": str(self.ttl_path),
            "inserted": inserted,
            "skipped": skipped,
            "inserted_count": len(inserted),
            "skipped_count": len(skipped),
        }


class AgentInsert:
    def __init__(
        self,
        modified_ttl_path,
        summary_file_path,
        model=DEFAULT_MODEL,
        allow_traversal=True,
    ):
        load_dotenv()
        self.client = llm_client
        self.modified_ttl_path = Path(modified_ttl_path)
        self.summary_file_path = Path(summary_file_path)
        self.summary = self.summary_file_path.read_text(encoding="utf-8")
        self.model = model
        self.allow_traversal = allow_traversal
        generation_mode = (
            "TRAVERSAL + INSERTION TOOLS"
            if allow_traversal
            else "INSERTION TOOL ONLY"
        )
        self.tools = AgentInsertionTools(
            self.modified_ttl_path,
            generated_by=model,
            generation_mode=generation_mode,
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            }
        ]

        # sliding window scratchpad, capped to last 6 tool observations
        self.scratchpad = []

    def _system_prompt(self):
        if not self.allow_traversal:
            return dedent(
                f"""
                You are an ontology reconstruction insertion agent.

                Reconstruct the missing ontology classes described in the summary.
                Traversal is unavailable in this experiment.

                Summary:
                {self.summary}

                Tool:
                - insert_class_batch(classes)

                Insert the missing classes in one batch. Use the class names,
                hierarchy, labels, and descriptions supported by the summary.
                Do not output Turtle or markdown.

                Every response must match exactly one of these shapes.

                Tool call:
                Thought: concise reason
                Action: insert_class_batch
                Action Input: {{"classes": [{{"class_name": "...",
                  "parent_class_name": "...", "label": "...",
                  "comment": "..."}}]}}
                PAUSE

                Completion:
                Final Answer: inserted=<count>; classes=[ClassName, ...]

                Do not add text before or after the selected shape.
                """
            ).strip()

        return dedent(
            f"""
            You are an ontology reconstruction insertion agent.

            Reconstruct the missing ontology classes described in the summary.
            Use the traversal tools to find the existing parent for the missing
            community, then insert the community in one batch.

            Summary:
            {self.summary}

            Tools:
            - query_subclass(parent_class_name): returns direct subclass names.
            - inspect_class(target_class_name): returns basic class details.
            - insert_class_batch(classes): inserts missing classes.

            Start traversal at Concept. Use the summary for the missing class
            names, hierarchy, labels, and descriptions. Once the existing parent
            is identified, insert all missing classes in one batch.

            Rules:
            - Use one tool call per assistant response.
            - Do not output Turtle or markdown.

            Every response must match exactly one of these shapes.

            Direct-subclass lookup:
            Thought: concise reason
            Action: query_subclass
            Action Input: {{"parent_class_name": "ClassName"}}
            PAUSE

            Class inspection:
            Thought: concise reason
            Action: inspect_class
            Action Input: {{"target_class_name": "ClassName"}}
            PAUSE

            Insertion:
            Thought: concise reason
            Action: insert_class_batch
            Action Input: {{"classes": [{{"class_name": "...",
              "parent_class_name": "...", "label": "...",
              "comment": "..."}}]}}
            PAUSE

            Completion:
            Final Answer: inserted=<count>; classes=[ClassName, ...]

            Do not add text before or after the selected shape.
            """
        ).strip()

    def send_messages(self, message):
        messages = [self.messages[0]]
        if self.scratchpad:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Compact traversal state so far:\n"
                        + "\n".join(self.scratchpad[-6:])
                    ),
                }
            )
        messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
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
                "Reconstruct and insert the missing ontology community described in "
                "the summary. Traverse from Concept first and follow one of the "
                "required response shapes exactly."
            )
            known_tools = {
                "query_subclass": self.tools.query_subclass,
                "inspect_class": self.tools.inspect_class,
                "insert_class_batch": self.tools.insert_class_batch,
            }
        else:
            next_message = (
                "Reconstruct and insert the missing ontology community described "
                "in the summary using insert_class_batch. No traversal or "
                "inspection tools are available. Follow one of the required "
                "response shapes exactly."
            )
            known_tools = {
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
            compact_json = json.dumps(compact_result, ensure_ascii=False)
            self.scratchpad.append(f"{action} -> {compact_json}")
            if self.allow_traversal:
                next_message = (
                    "Continue from the compact traversal state. If the parent is "
                    "grounded, insert the missing community in one batch. Follow "
                    "one of the required response shapes exactly."
                )
            else:
                next_message = (
                    "Continue using only insert_class_batch. Correct any insertion "
                    "error using the summary and insert the missing community in "
                    "one batch. Follow one of the required response shapes exactly."
                )

        return None
