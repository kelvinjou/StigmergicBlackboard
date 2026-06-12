import shutil
import sys
from pathlib import Path
import rdflib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.bl_insert import BaselineInsert
from PrunedReconstruction.verif_metrics import validate_ttl

SRC_TTL = "dataset/baseline/WayfindingTechnique/modified_original.ttl"
DEST_TTL = "dataset/baseline/WayfindingTechnique/reinserted.ttl"
SUMMARY = "dataset/baseline/WayfindingTechnique/summary.txt"

bi = BaselineInsert(
    modified_ttl_path=SRC_TTL,
    summary_file_path=SUMMARY
)
output = bi.send_messages("ONLY OUTPUT THE ADDITIONAL TTL SYNTAX YOU GENERATE BASED ON DESCRIPTIVE SUMMARY PROVIDED IN THE FINAL ANSWER.")


# create copy of the modified_original.ttl firstte
shutil.copy(SRC_TTL, DEST_TTL)

def extract_md_content(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()

# add on the new ontology relations
additions = extract_md_content(str(output))
with open(DEST_TTL, "a") as file:
    file.write(
"""
#######################################
# BASELINE GENERATION (PURE LLM) OUTPUT
#######################################
\n""" + additions)
# validate     
validate_ttl(DEST_TTL)

# run script with: Python3 PrunedReconstruction/verif_metrics.py PrunedReconstruction/insertions/insert_into_mod.py

