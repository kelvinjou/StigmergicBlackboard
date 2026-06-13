import os

from dotenv import load_dotenv
from openai import OpenAI

DEFAULT_MODEL = "moonshotai/kimi-k2.6"

# Similar to BaselineInsert, but instead of having OpenAI generate .ttl file, it will
# generate SPARQL operations (insert/delete/update)to reduce write overhead
# the SPARQL would then get parsed into the Graph using RDFLib
class SparQLInsert:
    def __init__(self, modified_ttl_path, summary_file_path, model=DEFAULT_MODEL):
        # load in the graph, and then insert elems using SparQL commands
        
        # might be better to just write out SPARQL commands than actual ttl source file. 
        # will convert it over anyways

        # give it a Graph or the raw source file?
        # give it the raw source file, input would be the same, but output would be less?
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                             base_url="https://integrate.api.nvidia.com/v1"
                            )
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
                    "Root class name: 'Concept'\n\n"
                    "Current ontology TTL:\n"
                    f"{self.modified_ttl_path}\n\n"
                    "Create additional components to the ontology, based on the description"
                    f"{self.summary}\n\n"
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
    message = """
        ONLY OUTPUT SPARQL OPERATIONS YOU GENERATE BASED ON DESCRIPTIVE SUMMARY
        PROVIDED IN THE FINAL ANSWER.
        Output shape: ```sparql [OPERATION]```
        """
    response = llm.send_messages(message)
    print(response)

    # will also need a function that verifies SPARQL operation calls if they're valid or not
