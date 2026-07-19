from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from llm.lmstudio_llm import LMStudioLLM
from src.generate_sparQL import _format_sparql_response

BASELINE_SYSTEM_PROMPT_PATH = PROJECT_ROOT / "llm/prompts/baseline_sys_prompt.md"
ONTOLOGY_PATH = PROJECT_ROOT / "_raw_inputs/simplified_xr.ttl"
EVIDENCE_PATH = PROJECT_ROOT / "_raw_inputs/summary.txt"

# ONTOLOGY_PATH = PROJECT_ROOT / "_raw_inputs/enhanced_xr.ttl"
# EVIDENCE_PATH = PROJECT_ROOT / "_raw_inputs/summary_for_xr_enhanced.txt"

raw_ttl = ONTOLOGY_PATH.read_text(encoding="utf-8")
with open(EVIDENCE_PATH, "r") as file:
    for evidence in file:
        claim = evidence.strip()
        if not claim:
            continue

        llm = LMStudioLLM(
            system_prompt_path=BASELINE_SYSTEM_PROMPT_PATH,
            response_format=False,
            formatter=None,
        )
        start = time.time()


        result = llm.send_messages(
            f"""
            ontology: {raw_ttl}
            source claim: {claim}

            Return only the final fenced SPARQL code block. Do not include analysis.
            """,
            max_tokens=3000, # max output tokens
            temperature=0.0,
        )
        print(_format_sparql_response(result))

        end = time.time()

        print(f"IN: {llm.prompt_tokens}")
        print(f"OUT: {llm.completion_tokens}")
        print(f"Total: {llm.total_tokens}")
        print(f"Finished in: {end - start}")