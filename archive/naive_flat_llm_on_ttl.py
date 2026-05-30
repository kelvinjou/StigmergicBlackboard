from openai import OpenAI
from dotenv import load_dotenv
import os
import time

from agent import print_token_usage

# NO SYSTEM PROMPT, NO AGENT
class TTLFlatLLMCall:
    def __init__(self):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                             base_url="https://integrate.api.nvidia.com/v1"
                            )
        self.ttl_content = open("enhanced_xr.ttl", "r").read()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.messages.append(
            {
                "role": "system",
                "content": "TTL knowledge graph: " + self.ttl_content
            }
        )

    def send_messages(self, message):
        self.messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model="moonshotai/kimi-k2.6",
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
    start = time.time()
    llm = TTLFlatLLMCall()
    message = "What does the knowledge graph say about head mounted display?"
    response = llm.send_messages(message)
    end = time.time()
    print(response)
    print_token_usage(llm)
    print(f"Executed in {end - start} seconds.")
