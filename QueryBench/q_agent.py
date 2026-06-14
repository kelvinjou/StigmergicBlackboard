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
                "content": "Root class name: 'Concept' " + self.system_msg
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
    
def _extract_action(message):
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

def _extract_answer(message):
    answer_match = re.search(
        r"(?ms)^(?:Final Answer|Answer):\s*(.+?)(?=\n(?:Thought|Action|Action Input):|\Z)",
        message,
    )
    if answer_match:
        return answer_match.group(1).strip()

    return None

def _normalize_action_input(action_input):
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

def _print_token_usage(agent):
    print(
        "Token usage: "
        f"prompt={agent.prompt_tokens}, "
        f"completion={agent.completion_tokens}, "
        f"total={agent.total_tokens}"
    )

def agent_query(user_input, max_turns=10):
    agent = QueryAgent()
    tools = Tools()
    next_message = user_input

    known_tools = {
        "query_subclass": tools.query_subclass,
        "inspect_class": tools.inspect_class,
        "get_class_info": tools.inspect_class,
        "recurse_n_layers": tools.recurse_n_layers,
    }

    for _ in range(max_turns):
        response = agent.send_messages(next_message)
        print(response)
        print()

        answer = _extract_answer(response)
        if answer:
            _print_token_usage(agent)
            return answer

        action, action_input = _extract_action(response)

        if not action:
            _print_token_usage(agent)
            return response

        if action not in known_tools:
            next_message = (
                f"Observation: Unknown tool '{action}'. "
                f"Available tools: {', '.join(known_tools)}"
            )
            continue

        tool_input = _normalize_action_input(action_input)
        try:
            if isinstance(tool_input, dict):
                result = known_tools[action](**tool_input)
            else:
                result = known_tools[action](tool_input)
        except Exception as exc:
            result = {"error": str(exc), "tool": action}
        next_message = "Observation: " + json.dumps(result, ensure_ascii=False)

    _print_token_usage(agent)
    return None

# QUERY ONLY
if __name__ == "__main__":
    start = time.time()
    agent_query("What are head mounted displays?")
    end = time.time()
    print(f"Executed in {end - start} seconds.")
