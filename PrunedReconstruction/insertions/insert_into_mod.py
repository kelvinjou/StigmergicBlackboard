import shutil
import sys
from pathlib import Path

import rdflib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.baseline_insert import BaselineInsert

SRC_TTL = "dataset/WayfindingTechnique/modified_original.ttl"
DEST_TTL = "dataset/WayfindingTechnique/reinserted.ttl"
SUMMARY = "dataset/WayfindingTechnique/summary.txt"

bi = BaselineInsert(
    modified_ttl_path=SRC_TTL,
    summary_file_path=SUMMARY
)
output = bi.send_messages("ONLY OUTPUT THE ADDITIONAL TTL SYNTAX YOU GENERATE BASED ON DESCRIPTIVE SUMMARY PROVIDED IN THE FINAL ANSWER.")


# create copy of the modified_original.ttl firstte
shutil.copy(SRC_TTL, DEST_TTL)

def extract_ttl_content(text: str) -> str:
    return text.strip().removeprefix("```turtle").removesuffix("```").strip()

# add on the new ontology relations
additions = extract_ttl_content(str(output))
with open(DEST_TTL, "a") as file:
    file.write(
        """
        #######################################
        # BASELINE GENERATION (PURE LLM) OUTPUT
        #######################################
        \n
        """ +
        additions)