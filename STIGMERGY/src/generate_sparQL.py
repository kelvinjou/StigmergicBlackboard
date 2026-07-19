
# get strength > x, then apply top k Need a better way later on
"""
1. filter jsonl strength > 2
2. apply top K
3. retrieve the blurb array. (need some prompt engineering to format all the array values properly)
4. 
"""

from pathlib import Path
import json
import heapq
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from llm.lmstudio_llm import LMStudioLLM

BLACKBOARD_PATH = PROJECT_ROOT / "_raw_outputs/blackboard.jsonl"
SPARQL_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "llm/prompts/sparQL_generation_sys_prompt.md"
SPARQL_FENCE_PATTERN = re.compile(r"(?is)```sparql\s*(.*?)\s*```")
PREFIX_PATTERN = re.compile(r"(?im)^\s*PREFIX\s+\w+:\s*<[^>]+>\s*$")
INSERT_PATTERN = re.compile(r"(?i)INSERT\s+DATA\s*\{")

# apply minimum strength filtering then get top K
def strongest_communities(minimum: int, k: int) -> list[dict]:
    with open(BLACKBOARD_PATH, "r", encoding="utf-8") as file:
        # filter out commnuities with low strength
        qualifiers = (
            record
            for line in file
            if line.strip()
            and (record := json.loads(line))["strength"] >= minimum
        )

        # get top K
        return heapq.nlargest(
            k,
            qualifiers,
            key=lambda record: record["strength"],
        )
    
# a blank new LLM call per K community, and return SparQL command string
def retrieve_blurbs(communities: list[dict]) -> str:
    # a fancier way of "append every "text"" in list(community[blurb])"
    text_evidence = [
        blurb["text"]
        for community in communities
        for blurb in community["blurb"]
    ]
    community_context = [
        {
            "uri": community["community_id"],
            "description": community["community"],
            "strength": community["strength"],
        }
        for community in communities
    ]

    agent = LMStudioLLM(
        system_prompt_path=SPARQL_SYSTEM_PROMPT_PATH,
        response_format=False,
        formatter=None,
    )
    response = agent.send_messages(
        json.dumps(
            {
                "communities": community_context,
                "evidence": text_evidence,
            },
            ensure_ascii=True,
            indent=2,
        ),
        max_tokens=1500,
        temperature=0.0,
    )

    return _format_sparql_response(response)


def _format_sparql_response(response: str) -> str:
    return f"```sparql\n{_extract_sparql_update(response)}\n```"


def _extract_sparql_update(response: str) -> str:
    fence_match = SPARQL_FENCE_PATTERN.search(response)
    if fence_match:
        response = fence_match.group(1)

    prefixes = [match.group(0).strip() for match in PREFIX_PATTERN.finditer(response)]
    insert_block = _extract_insert_data_block(response)
    if not insert_block:
        return "INSERT DATA { }"

    sparql = "\n".join([*dict.fromkeys(prefixes), "", insert_block]).strip()
    return re.sub(r"<(ex:[^>]+)>", r"\1", sparql)


def _extract_insert_data_block(text: str) -> str | None:
    match = INSERT_PATTERN.search(text)
    if not match:
        return None

    start = match.start()
    brace_start = text.find("{", match.end() - 1)
    if brace_start == -1:
        return None

    depth = 0
    for index in range(brace_start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1].strip()
    return None
        


if __name__ == "__main__":
    communities = strongest_communities(minimum=2, k=3)
    print(retrieve_blurbs(communities=communities))
