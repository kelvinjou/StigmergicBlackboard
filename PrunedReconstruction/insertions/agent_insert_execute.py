import shutil
import sys
import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.insertions.agent_insert import AgentInsert, DEFAULT_MODEL
from PrunedReconstruction.verif_metrics import validate_ttl


DEFAULT_EXPERIMENT_TYPE = "agent"


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


def run_agent_insert(
    experiment_type=DEFAULT_EXPERIMENT_TYPE,
    community=None,
    dataset_dir=None,
    max_turns=12,
    model=DEFAULT_MODEL,
):
    """
    Rebuild reinserted.ttl from the corresponding modified_original.ttl, then
    let the agent append reconstructed ontology chunks to reinserted.ttl.
    """
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
    print(f"Agent insertion target: {dest_ttl}")

    agent_insert = AgentInsert(
        modified_ttl_path=dest_ttl,
        summary_file_path=summary,
        model=model,
    )
    result = agent_insert.run(max_turns=max_turns)

    print(result)
    print(
        "Token usage: "
        f"prompt={agent_insert.prompt_tokens}, "
        f"completion={agent_insert.completion_tokens}, "
        f"total={agent_insert.total_tokens}"
    )

    validate_ttl(dest_ttl)
    return agent_insert, result, paths


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Insert a pruned ontology community into the matching reinserted.ttl "
            "copy using the traversal-based agent."
        )
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
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    ai, output, paths = run_agent_insert(
        experiment_type=args.experiment_type,
        community=args.community,
        dataset_dir=args.dataset_dir,
        max_turns=args.max_turns,
        model=args.model,
    )
    SRC_TTL = paths["src_ttl"]
    DEST_TTL = paths["dest_ttl"]
    SUMMARY = paths["summary"]
