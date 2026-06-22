import argparse
import re
import shutil
import sys
from pathlib import Path

from rdflib import Graph
from rdflib.plugins.sparql.parser import parseUpdate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.sparql_insert import DEFAULT_MODEL, SparQLInsert
from PrunedReconstruction.verif_metrics import validate_ttl


DEFAULT_EXPERIMENT_TYPE = "sparql"


def dataset_paths(experiment_type=DEFAULT_EXPERIMENT_TYPE, community=None, dataset_dir=None):
    if dataset_dir is None:
        if not community:
            raise ValueError("Pass --community or --dataset-dir.")
        dataset_dir = PROJECT_ROOT / "dataset" / experiment_type / community
    else:
        dataset_dir = Path(dataset_dir)

    return {
        "src_ttl": dataset_dir / "modified_original.ttl",
        "dest_ttl": dataset_dir / "reinserted.ttl",
        "summary": dataset_dir / "summary.txt",
    }


def is_valid_sparql_update(query_string):
    try:
        parseUpdate(query_string)
        return True
    except Exception as exc:
        print(f"Syntax Error: {exc}")
        return False


def extract_md_content(text):
    text = str(text).strip()
    fenced_match = re.search(r"```(?:\w+)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced_match:
        return fenced_match.group(1).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def run_sparql_insert(
    experiment_type=DEFAULT_EXPERIMENT_TYPE,
    community=None,
    dataset_dir=None,
    model=DEFAULT_MODEL,
):
    paths = dataset_paths(
        experiment_type=experiment_type,
        community=community,
        dataset_dir=dataset_dir,
    )
    src_ttl = paths["src_ttl"]
    dest_ttl = paths["dest_ttl"]
    summary = paths["summary"]

    if not src_ttl.exists():
        raise FileNotFoundError(f"Missing source TTL: {src_ttl}")
    if not summary.exists():
        raise FileNotFoundError(f"Missing summary file: {summary}")

    dest_ttl.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_ttl, dest_ttl)
    print(f"Copied source ontology: {src_ttl}")
    print(f"SPARQL insertion target: {dest_ttl}")

    sparql_insert = SparQLInsert(
        modified_ttl_path=src_ttl,
        summary_file_path=summary,
        model=model,
    )
    raw_output = sparql_insert.send_messages(
        "Generate the SPARQL insertion using the required output shape exactly."
    )
    sparql_output = extract_md_content(raw_output)
    sparql_query_valid = is_valid_sparql_update(sparql_output)

    if sparql_query_valid:
        graph = Graph()
        graph.parse(dest_ttl, format="turtle")
        graph.update(sparql_output)
        graph.serialize(destination=dest_ttl, format="turtle")
        print("The generated SPARQL update is valid. ✅")

    print(raw_output)
    print(
        "Token usage: "
        f"prompt={sparql_insert.prompt_tokens}, "
        f"completion={sparql_insert.completion_tokens}, "
        f"total={sparql_insert.total_tokens}"
    )

    validate_ttl(dest_ttl)
    return sparql_insert, raw_output, paths, sparql_query_valid


def parse_args():
    parser = argparse.ArgumentParser(
        description="Insert a pruned ontology community using generated SPARQL update operations."
    )
    parser.add_argument("--experiment-type", default=DEFAULT_EXPERIMENT_TYPE)
    parser.add_argument(
        "--community",
        default=None,
        help="Pruned community name under dataset/<experiment-type>/.",
    )
    parser.add_argument(
        "--dataset-dir",
        default=None,
        help="Optional explicit directory containing modified_original.ttl and summary.txt.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    si, output, paths, sparql_query_valid = run_sparql_insert(
        experiment_type=args.experiment_type,
        community=args.community,
        dataset_dir=args.dataset_dir,
        model=args.model,
    )
    SRC_TTL = paths["src_ttl"]
    DEST_TTL = paths["dest_ttl"]
    SUMMARY = paths["summary"]
