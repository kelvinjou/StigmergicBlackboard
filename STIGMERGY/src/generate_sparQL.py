
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

BLACKBOARD_PATH = Path("_raw_outputs/blackboard.jsonl")
SPARQL_SYSTEM_PROMPT_PATH = Path("llm/sparQL_generation_sys_prompt.md")

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
    
# a blank new LLM call per K community?
def retrieve_blurbs(communities: list[dict]):
    system_prompt = SPARQL_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

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

    user_prompt = json.dumps(
        {
            "communities": community_context,
            "evidence": text_evidence,
        },
        ensure_ascii=True,
        indent=2,
    )

    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]
        


if __name__ == "__main__":
    communities = strongest_communities(minimum=2, k=1)
    retrieve_blurbs(communities=communities)
