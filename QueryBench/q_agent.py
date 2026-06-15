import json
import importlib.util
import os
from pathlib import Path
import re
import time

from openai import OpenAI
from dotenv import load_dotenv

if __package__:
    from .tools import Tools
else:
    tools_path = Path(__file__).with_name("tools.py")
    spec = importlib.util.spec_from_file_location("querybench_tools", tools_path)
    tools_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools_module)
    Tools = tools_module.Tools

class QueryAgent:
    def __init__(self):
        load_dotenv()
        self.client = OpenAI(api_key=os.getenv("NVIDIA_API_KEY"),
                             base_url="https://integrate.api.nvidia.com/v1"
                            )
        self.system_msg = open("QueryBench/system_prompt.md", "r").read()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.messages = []
        self.messages.append(
            {
                "role": "system",
                "content": 
                    """
                    You are a knowledge-graph question-answering assistant for an extended reality (XR) ontology.

                    You will be given:
                    - A user question about XR concepts in the ontology.

                    Your job is to answer the question using only ontology information. Do not invent ontology
                    triples, class definitions, labels, comments, or relationships that were not
                    returned in an Observation.

                    When you have enough observations, respond:
                    Final Answer: {your complete answer to the question}
                    """ + 
                    "Root class name: 'Concept' " + self.system_msg
            }
        )
        self.tools = Tools()
        self.known_tools = {
            "query_subclass": self.tools.query_subclass,
            "inspect_class": self.tools.inspect_class,
            "get_class_info": self.tools.inspect_class,
            "recurse_n_layers": self.tools.recurse_n_layers,
        }

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

    def _extract_action(self, message):
        action_regex = re.compile(r"^Action:\s*(.+?)\s*$")
        input_regex = re.compile(r"^Action Input:\s*(.+?)\s*$")

        action = None
        action_input = None

        for line in message.split("\n"):
            action_match = action_regex.match(line)
            input_match = input_regex.match(line)

            if action_match:
                action = action_match.group(1).strip()
            elif input_match:
                action_input = input_match.group(1).strip()

        return action, action_input

    def _extract_answer(self, message):
        answer_match = re.search(
            r"(?ms)^(?:Final Answer|Answer):\s*(.+?)(?=\n(?:Thought|Action|Action Input):|\Z)",
            message,
        )
        if answer_match:
            return answer_match.group(1).strip()

        return None

    def _normalize_action_input(self, action_input):
        if action_input is None:
            return None

        action_input = action_input.strip()
        if not action_input:
            return action_input

        try:
            parsed = json.loads(action_input)
        except json.JSONDecodeError:
            return action_input.strip("\"'")

        if isinstance(parsed, dict) and len(parsed) == 1:
            for key in ("parent_class", "parent_class_name", "target_class", "target_class_name"):
                if key in parsed:
                    return parsed[key]

        return parsed

    def _print_token_usage(self):
        print(
            "Token usage: "
            f"prompt={self.prompt_tokens}, "
            f"completion={self.completion_tokens}, "
            f"total={self.total_tokens}"
        )

    def query(self, user_input, max_turns=10):
        next_message = user_input

        for _ in range(max_turns):
            response = self.send_messages(next_message)
            print(response)
            print()

            answer = self._extract_answer(response)
            if answer:
                self._print_token_usage()
                return answer

            action, action_input = self._extract_action(response)

            if not action:
                self._print_token_usage()
                return response

            if action not in self.known_tools:
                next_message = (
                    f"Observation: Unknown tool '{action}'. "
                    f"Available tools: {', '.join(self.known_tools)}"
                )
                continue

            tool_input = self._normalize_action_input(action_input)
            try:
                if isinstance(tool_input, dict):
                    result = self.known_tools[action](**tool_input)
                else:
                    result = self.known_tools[action](tool_input)
            except Exception as exc:
                result = {"error": str(exc), "tool": action}
            next_message = "Observation: " + json.dumps(result, ensure_ascii=False)

        self._print_token_usage()
        return None

def agent_query(user_input, max_turns=10):
    agent = QueryAgent()
    return agent.query(user_input, max_turns=max_turns)

# QUERY ONLY
if __name__ == "__main__":
    start = time.time()
    qa = QueryAgent()
    qa.query("What are head mounted displays?")
    end = time.time()
    print(f"Executed in {end - start} seconds.")
