import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL
from LLMCompletionWrappers import client as llm_client

DEFAULT_MODEL = LLM_MODEL

class BaselineInsert:
    def __init__(self, modified_ttl_path, summary_file_path, model=DEFAULT_MODEL):
        load_dotenv()
        self.client = llm_client
        self.model = model
        self.modified_ttl_path = open(modified_ttl_path, "r").read()
        self.summary = open(summary_file_path, "r").read()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.messages.append(
            {
                "role": "system",
                "content": (
                    "Reconstruct the missing ontology classes described by the summary.\n\n"
                    "Current ontology TTL:\n"
                    f"{self.modified_ttl_path}\n\n"
                    "Summary:\n"
                    f"{self.summary}\n\n"
                    "Required output shape:\n"
                    ":ClassName a owl:Class ;\n"
                    "    rdfs:label \"Class label\"@en ;\n"
                    "    rdfs:comment \"Class description\"@en ;\n"
                    "    rdfs:subClassOf :ParentClassName .\n\n"
                    "Repeat that block for each missing class. Return only those "
                    "Turtle blocks. Do not include prefixes, markdown fences, prose, "
                    "or the existing ontology."
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
    SRC_TTL = "dataset/baseline/WayfindingTechnique/modified_original.ttl"
    SUMMARY = "dataset/baseline/WayfindingTechnique/summary.txt"
    llm = BaselineInsert(
        modified_ttl_path=SRC_TTL,
        summary_file_path=SUMMARY
    )
    message = "Generate the missing classes using the required output shape exactly."
    response = llm.send_messages(message)
    print(response)
