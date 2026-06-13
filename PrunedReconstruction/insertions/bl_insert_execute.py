import argparse
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.bl_insert import BaselineInsert, DEFAULT_MODEL
from PrunedReconstruction.verif_metrics import validate_ttl


DEFAULT_EXPERIMENT_TYPE = "baseline"


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


def extract_md_content(text):
    text = str(text).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def run_baseline_insert(
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
    print(f"Baseline insertion target: {dest_ttl}")

    baseline_insert = BaselineInsert(
        modified_ttl_path=src_ttl,
        summary_file_path=summary,
        model=model,
    )
    output = baseline_insert.send_messages(
        "ONLY OUTPUT THE ADDITIONAL TTL SYNTAX YOU GENERATE BASED ON DESCRIPTIVE SUMMARY PROVIDED IN THE FINAL ANSWER."
    )

    additions = extract_md_content(output)
    with open(dest_ttl, "a", encoding="utf-8") as ttl_file:
        ttl_file.write(
            "\n\n"
            "#######################################\n"
            "# BASELINE GENERATION (PURE LLM) OUTPUT\n"
            "#######################################\n\n"
            f"{additions}\n"
        )

    print(output)
    print(
        "Token usage: "
        f"prompt={baseline_insert.prompt_tokens}, "
        f"completion={baseline_insert.completion_tokens}, "
        f"total={baseline_insert.total_tokens}"
    )

    validate_ttl(dest_ttl)
    return baseline_insert, output, paths


def parse_args():
    parser = argparse.ArgumentParser(
        description="Insert a pruned ontology community using the baseline LLM TTL strategy."
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
    bi, output, paths = run_baseline_insert(
        experiment_type=args.experiment_type,
        community=args.community,
        dataset_dir=args.dataset_dir,
        model=args.model,
    )
    SRC_TTL = paths["src_ttl"]
    DEST_TTL = paths["dest_ttl"]
    SUMMARY = paths["summary"]
