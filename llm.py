from openai import OpenAI
from dotenv import load_dotenv
import os


class Agent:
    def __init__(self):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                             base_url="https://integrate.api.nvidia.com/v1"
                            )
        self.system_msg = open("system_prompt.md", "r").read()
        self.messages = []
        self.messages.append({"role": "system", "content": self.system_msg})

    def send_messages(self, message):
        self.messages.append({"role": "user", "content": str(message)})
        response = self.client.chat.completions.create(
            model="moonshotai/kimi-k2.6",
            messages=self.messages
        )
        return response.choices[0].message.content
    
# known_tools = {
#     ""
# }

if __name__ == "__main__":
    agent = Agent()
    message = "Write a 10 word joke"
    response = agent.send_messages(message)
    print(response)