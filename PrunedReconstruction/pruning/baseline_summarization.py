import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL
from LLMCompletionWrappers import client as llm_client


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
