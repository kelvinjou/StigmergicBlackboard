import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL
from LLMCompletionWrappers import client as llm_client
from PrunedReconstruction.insertions.reconstruction_contract import EVIDENCE_RULES

DEFAULT_MODEL = LLM_MODEL

class SparQLInsert:
    def __init__(self, modified_ttl_path, summary_file_path, model=DEFAULT_MODEL):
        load_dotenv()
        self.client = llm_client
        self.model = model
        self.modified_ttl_path = Path(modified_ttl_path).read_text(encoding="utf-8")
        self.summary = Path(summary_file_path).read_text(encoding="utf-8")
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.messages.append(
            {
                "role": "system",
                "content": (
                    "Reconstruct the missing ontology RDF subgraph described by the summary.\n\n"
                    "Current ontology TTL:\n"
                    f"{self.modified_ttl_path}\n\n"
                    "Summary:\n"
                    f"{self.summary}\n\n"
                    f"{EVIDENCE_RULES}\n\n"
                    "Required output shape:\n"
                    "PREFIX : <ontology-default-namespace>\n"
                    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
                    "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
                    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                    "INSERT DATA {\n"
                    "  :ClassName a owl:Class ;\n"
                    "      rdfs:label \"Class label\"@en ;\n"
                    "      rdfs:comment \"Class description\"@en ;\n"
                    "      rdfs:subClassOf :ParentClassName ;\n"
                    "      :coveredInChapter :Ch4 ;\n"
                    "      :supportsTask :TaskName .\n"
                    "  :ExistingResource :somePredicate :ClassName .\n"
                    "}\n\n"
                    "The example predicates are illustrative. Use the actual default "
                    "namespace and include every missing triple explicitly supported "
                    "by the summary inside one INSERT DATA block, including incoming "
                    "or outgoing non-hierarchical assertions. Return only the SPARQL "
                    "update. Do not include markdown fences or prose."
                )
            }
        )
    def send_messages(self, message):
        self.messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages
        )
        content = response.choices[0].message.content
        self.messages.append({"role": "assistant", "content": content})
        if response.usage:
            self.prompt_tokens += response.usage.prompt_tokens or 0
            self.completion_tokens += response.usage.completion_tokens or 0
            self.total_tokens += response.usage.total_tokens or 0
        return content
    
if __name__ == "__main__":
    SRC_TTL = "dataset/sparql/WayfindingTechnique/modified_original.ttl"
    SUMMARY = "dataset/sparql/WayfindingTechnique/summary.txt"
    llm = SparQLInsert(
        modified_ttl_path=SRC_TTL,
        summary_file_path=SUMMARY
    )
    message = "Generate the SPARQL update for the missing RDF subgraph using the required output shape exactly."
    response = llm.send_messages(message)
    print(response)
