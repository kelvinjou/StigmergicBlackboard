import shutil
import sys
from pathlib import Path

from rdflib import Graph
from rdflib.plugins.sparql.parser import parseUpdate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.sparql_insert import SparQLInsert
from PrunedReconstruction.verif_metrics import validate_ttl

SRC_TTL = PROJECT_ROOT / "dataset" / "sparql" / "WayfindingTechnique" / "modified_original.ttl"
DEST_TTL = PROJECT_ROOT / "dataset" / "sparql" / "WayfindingTechnique" / "reinserted.ttl"
SUMMARY = PROJECT_ROOT / "dataset" / "sparql" / "WayfindingTechnique" / "summary.txt"

bi = SparQLInsert(
    modified_ttl_path=SRC_TTL,
    summary_file_path=SUMMARY
)
raw_output = bi.send_messages("""
    ONLY OUTPUT SPARQL OPERATIONS YOU GENERATE BASED ON DESCRIPTIVE SUMMARY
    PROVIDED IN THE FINAL ANSWER.
    Output shape: ```sparql [OPERATION]
        ```
    """)

shutil.copy(SRC_TTL, DEST_TTL)

g = Graph()
g.parse(DEST_TTL, format="turtle")

def is_valid_sparql_update(query_string):
    try:
        parseUpdate(query_string)
        return True
    except Exception as e:
        print(f"Syntax Error: {e}")
        return False

# print(f"This is the output:\n{raw_output}\n########")

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

# trimmed sparql
sparql_output = extract_md_content(str(raw_output))
# print(f"This is the TRIMMED output:\n{sparql_output}\n########")


if is_valid_sparql_update(sparql_output):
    print("The generated SPARQL update is valid. ✅")
    g.update(sparql_output)

    # save the updated graph as new
    g.serialize(destination=DEST_TTL, format="turtle")
    validate_ttl(DEST_TTL)


