import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLM_MODEL
from LLMCompletionWrappers import client as llm_client

class QueryBaseline:
    def __init__(self, model=LLM_MODEL):
        load_dotenv()
        self.client = llm_client
        self.model = model
        self.raw_ttl = open("/Users/kelvinjou/Documents/GitHub/OntologyAgent/enhanced_xr.ttl", "r").read()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.messages.append(
            {
                "role": "system",
                "content": (
                    """
                    You are a knowledge-graph question-answering assistant for an extended reality (XR) ontology.

                    You will be given:
                    - A user question about XR concepts in the ontology.

                    Your job is to answer the question using only ontology information. Do not invent ontology
                    triples, class definitions, labels, comments, or relationships that were not
                    returned in an Observation.

                    When you have enough observations, respond:
                    Final Answer: {your complete answer to the question}""" + 
                    "Current ontology TTL:\n"
                    f"{self.raw_ttl}\n"
                )
            }
        )
    def _print_token_usage(self):
        print(
            "Token usage: "
            f"prompt={self.prompt_tokens}, "
            f"completion={self.completion_tokens}, "
            f"total={self.total_tokens}"
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
        
        self._print_token_usage()
        return content
    
if __name__ == "__main__":
    start = time.time()
    qb = QueryBaseline()
    qb.send_messages("What are head mounted displays?")
    end = time.time()
    print(f"Executed in {end - start} seconds.")
