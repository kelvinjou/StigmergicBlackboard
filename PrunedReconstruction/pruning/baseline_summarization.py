from openai import OpenAI
from dotenv import load_dotenv
import os

class BaselineSummarization:
    def __init__(self):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                             base_url="https://integrate.api.nvidia.com/v1"
                            )
        self.raw_ttl = open("enhanced_xr.ttl", "r").read()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.max_tokens = 500
        self.messages.append(
            {
                "role": "system",
                "content": "Root class name: 'Concept'" + self.raw_ttl
            }
        )

    def send_messages(self, message):
        self.messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model="moonshotai/kimi-k2.6",
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
    message = "Generate a thorough description about Wayfinding Technique, and its relations with other communities in the ontology especially communities that are a subclass of it."
    response = agent.send_messages(message)
    print(response)


"""
`:WayfindingTechnique` occupies a **bridge position** in this ontology: it is fundamentally an interaction technique (process-oriented), but its effectiveness is entirely measured by its impact on human cognitive factors (particularly `:SpatialMemory`), and its implementation spans hardware displays, UI components, and design principles. Unlike `:SelectionTechnique` or `:ManipulationTechnique` which have more direct object targets, wayfinding is **meta-cognitive** — it supports the user's internal model of space rather than direct environmental change.
"""