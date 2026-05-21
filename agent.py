import json
import re

from llm import Agent
from tools import get_class_info, query_subclass
import time


def extract_action(message):
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


def extract_answer(message):
    answer_regex = re.compile(r"^(?:Final Answer|Answer):\s*(.+)$")

    for line in message.split("\n"):
        answer_match = answer_regex.match(line)
        if answer_match:
            return answer_match.group(1)

    return None


def normalize_action_input(action_input):
    if action_input is None:
        return None

    action_input = action_input.strip()
    if not action_input:
        return action_input

    try:
        parsed = json.loads(action_input)
    except json.JSONDecodeError:
        return action_input.strip("\"'")

    if isinstance(parsed, dict):
        for key in ("parent_class", "parent_class_name", "target_class", "target_class_name"):
            if key in parsed:
                return parsed[key]

    return parsed


def agent_query(user_input, max_turns=10):
    agent = Agent()
    next_message = user_input

    known_tools = {
        "query_subclass": query_subclass,
        "get_class_info": get_class_info,
    }

    for _ in range(max_turns):
        response = agent.send_messages(next_message)
        print(response)
        print()

        action, action_input = extract_action(response)

        if not action:
            answer = extract_answer(response) or response
            print_token_usage(agent)
            return answer

        if action not in known_tools:
            next_message = (
                f"Observation: Unknown tool '{action}'. "
                f"Available tools: {', '.join(known_tools)}"
            )
            continue

        result = known_tools[action](normalize_action_input(action_input))
        next_message = "Observation: " + json.dumps(result, ensure_ascii=False)

    print_token_usage(agent)
    return None


def print_token_usage(agent):
    print(
        "Token usage: "
        f"prompt={agent.prompt_tokens}, "
        f"completion={agent.completion_tokens}, "
        f"total={agent.total_tokens}"
    )


if __name__ == "__main__":
    start = time.time()
    agent_query("What does the knowledge graph say about head mounted display?")
    end = time.time()
    print(f"Executed in {end - start} seconds.")