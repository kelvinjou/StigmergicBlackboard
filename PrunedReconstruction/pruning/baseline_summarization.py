import sys
from pathlib import Path

from dotenv import load_dotenv
from rdflib import RDF, RDFS, OWL, Literal, URIRef

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL
from LLMCompletionWrappers import client as llm_client
from PrunedReconstruction.predicate_vocabulary import format_predicate_vocabulary


IGNORED_SUMMARY_PREDICATES = {
    RDF.type,
    RDFS.label,
    RDFS.comment,
    RDFS.subClassOf,
}


def _local_name(term):
    text = str(term)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    if "/" in text:
        return text.rstrip("/").rsplit("/", 1)[-1]
    return text


def _english_literal(graph, subject, predicate):
    values = list(graph.objects(subject, predicate))
    if not values:
        return None

    for value in values:
        if isinstance(value, Literal) and str(value.language).lower() == "en":
            return str(value)
    return str(values[0])


def _resource_label(graph, resource):
    return _english_literal(graph, resource, RDFS.label) or _local_name(resource)


def build_fallback_summary(graph, root_class):
    """Build a prose-only summary when the LLM returns no content.

    This intentionally does not emit Turtle, SPARQL, tables, or exact
    subject-predicate-object connector lists. It is a safety fallback for
    condition-B experiments where summaries should describe the community
    without handing insertion methods a structured reconstruction map.
    """

    root_label = _resource_label(graph, root_class)
    root_comment = _english_literal(graph, root_class, RDFS.comment)
    parents = sorted(
        _resource_label(graph, parent)
        for parent in graph.objects(root_class, RDFS.subClassOf)
        if isinstance(parent, URIRef)
    )
    direct_children = sorted(
        _resource_label(graph, child)
        for child in graph.subjects(RDFS.subClassOf, root_class)
        if isinstance(child, URIRef)
    )

    all_classes = {
        subject
        for subject in graph.subjects(RDF.type, OWL.Class)
        if isinstance(subject, URIRef)
    }
    all_classes.add(root_class)
    for subject, obj in graph.subject_objects(RDFS.subClassOf):
        if isinstance(subject, URIRef):
            all_classes.add(subject)
        if isinstance(obj, URIRef):
            all_classes.add(obj)

    descendant_count = max(len(all_classes) - 1, 0)
    relation_themes = sorted(
        {
            _local_name(predicate)
            for _subject, predicate, _object in graph
            if predicate not in IGNORED_SUMMARY_PREDICATES
        }
    )

    sentences = [
        f"{root_label} is the root of a detached ontology community.",
    ]
    if parents:
        sentences.append(
            f"In the broader taxonomy, it belongs under {', '.join(parents[:3])}."
        )
    if root_comment:
        sentences.append(root_comment)
    if direct_children:
        child_preview = ", ".join(direct_children[:8])
        suffix = " among others" if len(direct_children) > 8 else ""
        sentences.append(
            f"The community includes direct specializations such as {child_preview}{suffix}."
        )
    elif descendant_count:
        sentences.append(
            f"The community contains about {descendant_count} related class resources."
        )
    if relation_themes:
        theme_preview = ", ".join(relation_themes[:8])
        suffix = " and related context" if len(relation_themes) > 8 else ""
        sentences.append(
            f"Beyond hierarchy and labels, the detached material has broad relationship themes around {theme_preview}{suffix}."
        )
    sentences.append(
        "This summary is intentionally prose-only and omits exact connector triples."
    )
    return " ".join(sentences)


class BaselineSummarization:
    def __init__(
        self,
        ttl_path=PROJECT_ROOT / "enhanced_xr.ttl",
        model=LLM_MODEL,
    ):
        load_dotenv()
        self.client = llm_client
        self.model = model
        self.raw_ttl = Path(ttl_path).read_text(encoding="utf-8")
        self.predicate_vocabulary = format_predicate_vocabulary(ttl_path=ttl_path)
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.max_tokens = 1200
        self.messages.append(
            {
                "role": "system",
                "content": (
                    "Root class name: 'Concept'. Generate a prose-only summary "
                    "of the requested ontology community.\n\n"
                    "Do not output Turtle, SPARQL, JSON, CSV, tables, or "
                    "subject-predicate-object lists. Do not enumerate exact "
                    "connector triples. Do not provide a structured inventory of "
                    "relationships to reconstruct.\n\n"
                    "You may describe relationship themes at a high level, such "
                    "as the community's parent category, likely task area, chapter "
                    "context, evaluation context, or human-factor context, but "
                    "avoid saying that every named class has a specific exact "
                    "predicate/object pair. Distinguish conceptual relevance from "
                    "explicit ontology assertions when useful.\n\n"
                    f"{self.predicate_vocabulary}\n\n"
                    + self.raw_ttl
                )
            }
        )

    def send_messages(self, message):
        self.messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            max_tokens=self.max_tokens
        )
        content = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": content})
        if response.usage:
            self.prompt_tokens += response.usage.prompt_tokens or 0
            self.completion_tokens += response.usage.completion_tokens or 0
            self.total_tokens += response.usage.total_tokens or 0
        return content
    

if __name__ == "__main__":
    agent = BaselineSummarization()
    message = (
        "Generate a prose summary about Wayfinding Technique, its subclasses, "
        "and its broad role in the ontology. Do not list exact connector triples."
    )
    response = agent.send_messages(message)
    print(response)

# example output
"""
`:WayfindingTechnique` occupies a **bridge position** in this ontology: it is fundamentally an interaction technique (process-oriented), but its effectiveness is entirely measured by its impact on human cognitive factors (particularly `:SpatialMemory`), and its implementation spans hardware displays, UI components, and design principles. Unlike `:SelectionTechnique` or `:ManipulationTechnique` which have more direct object targets, wayfinding is **meta-cognitive** — it supports the user's internal model of space rather than direct environmental change.
"""
