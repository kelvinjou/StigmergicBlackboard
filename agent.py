import json
import re

from llm import Agent
from tools import Tools
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
    answer_match = re.search(
        r"(?ms)^(?:Final Answer|Answer):\s*(.+?)(?=\n(?:Thought|Action|Action Input):|\Z)",
        message,
    )
    if answer_match:
        return answer_match.group(1).strip()

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

    if isinstance(parsed, dict) and len(parsed) == 1:
        for key in ("parent_class", "parent_class_name", "target_class", "target_class_name"):
            if key in parsed:
                return parsed[key]

    return parsed


def agent_query(user_input, max_turns=10):
    agent = Agent()
    tools = Tools()
    next_message = user_input

    known_tools = {
        "query_subclass": tools.query_subclass,
        "inspect_class": tools.inspect_class,
        "get_class_info": tools.inspect_class,
        "recurse_n_layers": tools.recurse_n_layers,
        "add_evidence": tools.add_evidence,
    }

    for _ in range(max_turns):
        response = agent.send_messages(next_message)
        print(response)
        print()

        answer = extract_answer(response)
        if answer:
            print_token_usage(agent)
            return answer

        action, action_input = extract_action(response)

        if not action:
            print_token_usage(agent)
            return response

        if action not in known_tools:
            next_message = (
                f"Observation: Unknown tool '{action}'. "
                f"Available tools: {', '.join(known_tools)}"
            )
            continue

        tool_input = normalize_action_input(action_input)
        try:
            if isinstance(tool_input, dict):
                result = known_tools[action](**tool_input)
            else:
                result = known_tools[action](tool_input)
        except Exception as exc:
            result = {"error": str(exc), "tool": action}
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
    # What does the knowledge graph say about head mounted display?

    # Insertions
    # 30% of youth reported wearing head mounted display make them nauseous
    agent_query("Add new evidence that 15% of users say they prefer hand gesture tasks to be within 0.65 meters in front of them")
    end = time.time()
    print(f"Executed in {end - start} seconds.")
