import sys
from pathlib import Path

from dotenv import load_dotenv
from rdflib import OWL, RDF, RDFS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL
from LLMCompletionWrappers import client as llm_client


STRUCTURAL_SUMMARY_PREDICATES = {
    RDFS.label,
    RDFS.comment,
    RDFS.subClassOf,
}


def build_explicit_assertion_inventory(graph):
    """Return exact non-hierarchical triples for inclusion in summaries."""
    assertions = [
        triple
        for triple in graph
        if triple[1] not in STRUCTURAL_SUMMARY_PREDICATES
        and not (triple[1] == RDF.type and triple[2] == OWL.Class)
    ]
    lines = [
        "## Explicit RDF assertions to reconstruct",
        (
            "The following are asserted triples from the source ontology, not "
            "conceptual or inferred relationships:"
        ),
    ]
    for subject, predicate, obj in sorted(
        assertions, key=lambda triple: tuple(map(str, triple))
    ):
        lines.append(
            f"- {subject.n3(graph.namespace_manager)} "
            f"{predicate.n3(graph.namespace_manager)} "
            f"{obj.n3(graph.namespace_manager)} ."
        )
    if not assertions:
        lines.append("- None.")
    return "\n".join(lines)


class BaselineSummarization:
    def __init__(
        self,
        ttl_path=PROJECT_ROOT / "enhanced_xr.ttl",
        model=LLM_MODEL,
    ):
        load_dotenv()
        self.client = llm_client
        self.model = model
        self.raw_ttl = Path(ttl_path).read_text()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.max_tokens = 3000
        self.messages.append(
            {
                "role": "system",
                "content": (
                    "Root class name: 'Concept'. Summarize only relationships "
                    "asserted in the supplied ontology. Clearly distinguish exact "
                    "assertions from conceptual implications or possible future "
                    "relationships.\n\n"
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
        "Generate a thorough description about Wayfinding Technique, its "
        "subclasses, and its exact asserted relations with other communities."
    )
    response = agent.send_messages(message)
    print(response)

# example output
"""
`:WayfindingTechnique` occupies a **bridge position** in this ontology: it is fundamentally an interaction technique (process-oriented), but its effectiveness is entirely measured by its impact on human cognitive factors (particularly `:SpatialMemory`), and its implementation spans hardware displays, UI components, and design principles. Unlike `:SelectionTechnique` or `:ManipulationTechnique` which have more direct object targets, wayfinding is **meta-cognitive** — it supports the user's internal model of space rather than direct environmental change.
"""
