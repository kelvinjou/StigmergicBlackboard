from openai import OpenAI
from dotenv import load_dotenv
import os
from pathlib import Path

from llm.lmstudio_llm import _resolve_system_prompt


DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts/system_prompt.md"

class NvidiaNIMLLM:
    def __init__(self, system_prompt_path):
        load_dotenv()

        self.client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                             base_url="https://integrate.api.nvidia.com/v1"
        )
        self.system_prompt = _resolve_system_prompt(system_prompt_path)
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.messages.append(
            {
                "role": "system",
                "content": self.system_prompt
            }
        )

    def send_messages(self, message):
        self.messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model="deepseek-ai/deepseek-v4-flash",
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
    agent = NvidiaNIMLLM(
        system_prompt_path=DEFAULT_SYSTEM_PROMPT_PATH
    )
    message = "Write a 10 word joke"
    response = agent.send_messages(message)
    print(response)
