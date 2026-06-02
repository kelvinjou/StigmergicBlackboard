import shutil
import sys
from pathlib import Path
from rdflib import Graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.bl_insert import BaselineInsert
from PrunedReconstruction.verif_metrics import validate_ttl

SRC_TTL = "dataset/sparql/WayfindingTechnique/modified_original.ttl"
DEST_TTL = "dataset/sparql/WayfindingTechnique/reinserted.ttl"
SUMMARY = "dataset/sparql/WayfindingTechnique/summary.txt"

bi = BaselineInsert(
    modified_ttl_path=SRC_TTL,
    summary_file_path=SUMMARY
)
output = bi.send_messages("ONLY OUTPUT SPARQL OPERATIONS YOU GENERATE BASED ON DESCRIPTIVE SUMMARY PROVIDED IN THE FINAL ANSWER.")

# print(f"this is the output:\n{output}")
shutil.copy(SRC_TTL, DEST_TTL)

g = Graph()
g.parse(DEST_TTL, format="turtle")

# g.update(str(output))

# save the updated graph as new
g.serialize(destination=DEST_TTL, format="turtle")

#
# # create copy of the modified_original.ttl first
# shutil.copy(SRC_TTL, DEST_TTL)

# def extract_ttl_content(text: str) -> str:
#     return text.strip().removeprefix("```turtle").removesuffix("```").strip()

# # add on the new ontology relations
# additions = extract_ttl_content(str(output))
# with open(DEST_TTL, "a") as file:
#     file.write(
# """
# #######################################
# # BASELINE GENERATION (PURE LLM) OUTPUT
# #######################################
# \n""" + additions)

# # validate     
# validate_ttl(DEST_TTL)
