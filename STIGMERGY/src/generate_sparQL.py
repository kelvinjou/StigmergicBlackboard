
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

BLACKBOARD_DIR = PROJECT_ROOT / "_raw_outputs"
SPARQL_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "llm/prompts/sparQL_generation_sys_prompt.md"
SPARQL_FENCE_PATTERN = re.compile(r"(?is)```sparql\s*(.*?)\s*```")
PREFIX_PATTERN = re.compile(r"(?im)^\s*PREFIX\s+\w+:\s*<[^>]+>\s*$")
INSERT_PATTERN = re.compile(r"(?i)INSERT\s+DATA\s*\{")


def _blackboard_sort_key(path: Path) -> tuple[int, str]:
    match = re.fullmatch(r"bb(\d+)\.jsonl", path.name)
    if match:
        return int(match.group(1)), path.name
    return sys.maxsize, path.name


def _blackboard_paths(blackboard_path: str | Path | None) -> list[Path]:
    if blackboard_path is not None:
        return [Path(blackboard_path)]
    return sorted(BLACKBOARD_DIR.glob("bb*.jsonl"), key=_blackboard_sort_key)


def blackboard_paths(blackboard_path: str | Path | None = None) -> list[Path]:
    return _blackboard_paths(blackboard_path)


# apply minimum strength filtering then get top K
def strongest_communities(
    minimum: float,
    k: int,
    blackboard_path: str | Path | None = None,
) -> list[dict]:
    qualifiers = []
    for path in _blackboard_paths(blackboard_path):
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record["strength"] >= minimum:
                    record["blackboard_path"] = str(path)
                    qualifiers.append(record)

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
            "blackboard_path": community.get("blackboard_path"),
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

    # print(f"RAW RESPONSE: {response}")

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
