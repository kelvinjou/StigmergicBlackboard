# python3 PrunedReconstruction/benchmark_runs.py --all-communities

import argparse
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pandas as pd
from rdflib import Graph
from rdflib.plugins.sparql.parser import parseUpdate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import INPUT_CSV, TRIALS_PER_COMMUNITY
from PrunedReconstruction.insertions.agent_insert import AgentInsert, DEFAULT_MODEL
from PrunedReconstruction.insertions.bl_insert import BaselineInsert
from PrunedReconstruction.insertions.sparql_insert import SparQLInsert
from PrunedReconstruction.verif_metrics import validate_ttl

EXPERIMENT_TYPES = ("agent", "baseline", "sparql") #  "agent_no_traversal"
# EXPERIMENT_TYPES = ("agent",)

BENCHMARK_COLUMNS = [
    "run_id",
    "run_timestamp_utc",
    "community_pruned",
    "model",
    "experiment_type",
    "dataset_dir",
    "input_ttl_path",
    "detached_ground_truth_ttl_path",
    "modified_original_ttl_path",
    "summary_path",
    "output_ttl_path",
    "raw_model_output_path",
    "elapsed_seconds",
    "ttl_syntax_valid",
    "sparql_query_valid",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "ground_truth_alignment",
    "error",
]


def dataset_paths(
    dataset_root,
    experiment_type,
    community,
    run_id,
    preserve_trial_output=False,
):
    dataset_dir = Path(dataset_root) / experiment_type / community
    input_dataset_dir = dataset_dir
    if experiment_type == "agent_no_traversal":
        # Reuse the agent's exact pruning inputs so traversal is the only
        # experimental variable. Keep generated output in a separate directory.
        input_dataset_dir = Path(dataset_root) / "agent" / community

    output_name = (
        f"reinserted_{run_id}.ttl" if preserve_trial_output else "reinserted.ttl"
    )
    return {
        "dataset_dir": dataset_dir,
        "input_ttl": PROJECT_ROOT / "enhanced_xr.ttl",
        "detached_ttl": input_dataset_dir / "detached.ttl",
        "modified_ttl": input_dataset_dir / "modified_original.ttl",
        "summary": input_dataset_dir / "summary.txt",
        "output_ttl": dataset_dir / output_name,
        "raw_output": dataset_dir / f"raw_model_output_{run_id}.txt",
    }


def extract_md_content(text):
    text = str(text).strip()
    fenced_blocks = re.findall(r"```(?:\w+)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced_blocks:
        text = "\n;\n".join(block.strip() for block in fenced_blocks if block.strip())
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return text.strip()


def normalize_sparql_batch(text):
    text = extract_md_content(text)
    prefix_lines = []
    body_lines = []

    for line in text.splitlines():
        if re.match(r"^\s*(?:PREFIX|BASE)\b", line, flags=re.IGNORECASE):
            if line not in prefix_lines:
                prefix_lines.append(line)
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    body = re.sub(r"(?m)^\s*#.*\n?", "", body)
    body = re.sub(
        r"}\s*(?=(?:INSERT|DELETE|WITH|LOAD|CLEAR|CREATE|DROP|ADD|MOVE|COPY)\b)",
        "};\n\n",
        body,
        flags=re.IGNORECASE,
    )
    if not re.search(r"(?im)\bWHERE\s*\{", body):
        body = re.sub(r"(?im)^(\s*)INSERT\s*\{", r"\1INSERT DATA {", body)
        body = re.sub(r"(?im)^(\s*)DELETE\s*\{", r"\1DELETE DATA {", body)
    return "\n".join(prefix_lines + ["", body]).strip()


def is_valid_sparql_update(query_string):
    try:
        parseUpdate(query_string)
        return True
    except Exception as exc:
        print(f"SPARQL syntax error: {exc}")
        return False


def ensure_dataset_inputs(paths):
    for key in ("modified_ttl", "summary"):
        if not paths[key].exists():
            raise FileNotFoundError(f"Missing benchmark input: {paths[key]}")


def token_metrics(insert_runner):
    return {
        "input_tokens": getattr(insert_runner, "prompt_tokens", 0),
        "output_tokens": getattr(insert_runner, "completion_tokens", 0),
        "total_tokens": getattr(insert_runner, "total_tokens", 0),
    }


def write_raw_output(paths, output):
    paths["raw_output"].parent.mkdir(parents=True, exist_ok=True)
    paths["raw_output"].write_text(str(output), encoding="utf-8")


def is_rate_limit_error(exc):
    """Return True when an exception or one of its causes represents HTTP 429."""
    current = exc
    seen = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status_code = getattr(current, "status_code", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)

        if status_code == 429 or type(current).__name__ == "RateLimitError":
            return True

        current = current.__cause__ or current.__context__

    return False


def run_baseline(paths, model):
    ensure_dataset_inputs(paths)
    shutil.copy2(paths["modified_ttl"], paths["output_ttl"])

    baseline = BaselineInsert(
        modified_ttl_path=paths["modified_ttl"],
        summary_file_path=paths["summary"],
        model=model,
    )
    raw_output = baseline.send_messages(
        "Generate the missing classes using the required output shape exactly."
    )
    write_raw_output(paths, raw_output)
    additions = extract_md_content(raw_output)

    with open(paths["output_ttl"], "a", encoding="utf-8") as ttl_file:
        ttl_file.write(
            "\n\n"
            "#######################################\n"
            "# BASELINE GENERATION (PURE LLM) OUTPUT\n"
            "#######################################\n\n"
            f"{additions}\n"
        )

    return {
        **token_metrics(baseline),
        "ttl_syntax_valid": validate_ttl(paths["output_ttl"]),
        "sparql_query_valid": "",
    }


def run_sparql(paths, model):
    ensure_dataset_inputs(paths)
    shutil.copy2(paths["modified_ttl"], paths["output_ttl"])

    sparql_insert = SparQLInsert(
        modified_ttl_path=paths["modified_ttl"],
        summary_file_path=paths["summary"],
        model=model,
    )
    raw_output = sparql_insert.send_messages(
        "Generate the SPARQL insertion using the required output shape exactly."
    )
    write_raw_output(paths, raw_output)
    sparql_output = normalize_sparql_batch(raw_output)
    sparql_query_valid = is_valid_sparql_update(sparql_output)

    if sparql_query_valid:
        graph = Graph()
        graph.parse(paths["output_ttl"], format="turtle")
        graph.update(sparql_output)
        graph.serialize(destination=paths["output_ttl"], format="turtle")

    return {
        **token_metrics(sparql_insert),
        "ttl_syntax_valid": validate_ttl(paths["output_ttl"]),
        "sparql_query_valid": sparql_query_valid,
    }


def run_agent(paths, model, max_turns, allow_traversal=True):
    ensure_dataset_inputs(paths)
    paths["output_ttl"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["modified_ttl"], paths["output_ttl"])

    agent_insert = AgentInsert(
        modified_ttl_path=paths["output_ttl"],
        summary_file_path=paths["summary"],
        model=model,
        allow_traversal=allow_traversal,
    )
    raw_output = agent_insert.run(max_turns=max_turns)
    write_raw_output(paths, raw_output)

    return {
        **token_metrics(agent_insert),
        "ttl_syntax_valid": validate_ttl(paths["output_ttl"]),
        "sparql_query_valid": "",
    }


def run_one_benchmark(
    dataset_root,
    experiment_type,
    community,
    model,
    max_turns,
    run_id,
    preserve_trial_output=False,
):
    paths = dataset_paths(
        dataset_root,
        experiment_type,
        community,
        run_id,
        preserve_trial_output=preserve_trial_output,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    elapsed_seconds = 0
    metrics = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "ttl_syntax_valid": False,
        "sparql_query_valid": "",
    }
    error = ""

    start = perf_counter()
    try:
        if experiment_type == "agent":
            metrics.update(run_agent(paths, model, max_turns))
        elif experiment_type == "agent_no_traversal":
            metrics.update(
                run_agent(
                    paths,
                    model,
                    max_turns,
                    allow_traversal=False,
                )
            )
        elif experiment_type == "baseline":
            metrics.update(run_baseline(paths, model))
        elif experiment_type == "sparql":
            metrics.update(run_sparql(paths, model))
        else:
            raise ValueError(f"Unsupported experiment type: {experiment_type}")
    except Exception as exc:
        if is_rate_limit_error(exc):
            raise
        error = f"{type(exc).__name__}: {exc}"
        print(error)
        traceback.print_exc()
    finally:
        elapsed_seconds = perf_counter() - start

    return {
        "run_id": run_id,
        "run_timestamp_utc": started_at,
        "community_pruned": community,
        "model": model,
        "experiment_type": experiment_type,
        "dataset_dir": str(paths["dataset_dir"]),
        "input_ttl_path": str(paths["input_ttl"]),
        "detached_ground_truth_ttl_path": str(paths["detached_ttl"]),
        "modified_original_ttl_path": str(paths["modified_ttl"]),
        "summary_path": str(paths["summary"]),
        "output_ttl_path": str(paths["output_ttl"]),
        "raw_model_output_path": str(paths["raw_output"]),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "ttl_syntax_valid": metrics["ttl_syntax_valid"],
        "sparql_query_valid": metrics["sparql_query_valid"],
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "total_tokens": metrics["total_tokens"],
        "ground_truth_alignment": "",
        "error": error,
    }


def append_result(csv_path, row):
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    pd.DataFrame([row], columns=BENCHMARK_COLUMNS).to_csv(
        csv_path,
        mode="a",
        header=write_header,
        index=False,
    )
    return csv_path


def append_results(csv_path, rows):
    """Compatibility wrapper that persists each supplied row independently."""
    csv_path = Path(csv_path)
    for row in rows:
        append_result(csv_path, row)
    return csv_path


def read_ontology_csv(ontology_csv=INPUT_CSV):
    df = pd.read_csv(ontology_csv)
    df.columns = df.columns.str.strip()
    if "status" not in df.columns:
        df["status"] = ""
    df["status"] = df["status"].fillna("").astype(str).str.strip()
    return df


def mark_community_done(community, ontology_csv=INPUT_CSV):
    ontology_csv = Path(ontology_csv)
    df = read_ontology_csv(ontology_csv)
    mask = df["communities"].astype(str) == str(community)
    df.loc[mask, "status"] = "done"
    df.to_csv(ontology_csv, index=False)


def communities_from_args(args):
    df = read_ontology_csv(INPUT_CSV)
    community_status_df = df.loc[df["communities"].notna(), ["communities", "status"]]
    status_by_community = dict(
        zip(
            community_status_df["communities"].astype(str),
            community_status_df["status"].str.lower(),
        )
    )

    skipped_done = []
    communities = []
    for community in args.community:
        if (
            not args.include_done
            and status_by_community.get(str(community)) == "done"
        ):
            skipped_done.append(str(community))
            continue
        communities.append(community)

    if args.all_communities:
        if not args.include_done:
            df = df.loc[df["status"].str.lower() != "done"]

        communities.extend(
            df["communities"].dropna().astype(str).tolist()
        )

    if skipped_done:
        label = "community" if len(skipped_done) == 1 else "communities"
        print(f"Skipping already done {label}: {', '.join(skipped_done)}")

    return list(dict.fromkeys(communities))


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run insertion benchmarks and append one pandas CSV row per experiment run."
    )
    parser.add_argument(
        "--experiment",
        choices=EXPERIMENT_TYPES,
        nargs="+",
        default=list(EXPERIMENT_TYPES),
        help="Experiment type(s) to run. Defaults to all four.",
    )
    parser.add_argument(
        "--community",
        action="append",
        default=[],
        help="Pruned community to benchmark. Can be passed multiple times.",
    )
    parser.add_argument(
        "--all-communities",
        action="store_true",
        help="Benchmark every community listed in Ontology_IN.csv.",
    )
    parser.add_argument(
        "--pending-only",
        action="store_true",
        help="Deprecated; done rows are skipped unless --include-done is set.",
    )
    parser.add_argument(
        "--include-done",
        action="store_true",
        help=(
            "Include communities marked done. Useful for running a newly added "
            "experiment against existing pruning inputs."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--dataset-root", default=PROJECT_ROOT / "dataset")
    parser.add_argument("--csv", default=PROJECT_ROOT / "benchmark_results.csv")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--trials-per-community",
        type=positive_int,
        default=TRIALS_PER_COMMUNITY,
        help=(
            "Number of trials to run for each community. "
            f"Defaults to config.TRIALS_PER_COMMUNITY ({TRIALS_PER_COMMUNITY})."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    communities = communities_from_args(args)
    if not communities:
        raise SystemExit("Pass --community <name> or --all-communities.")

    rows_written = 0
    for community in communities:
        for trial_number in range(1, args.trials_per_community + 1):
            if args.run_id and args.trials_per_community == 1:
                run_id = args.run_id
            elif args.run_id:
                run_id = f"{args.run_id}-trial-{trial_number}"
            else:
                run_id = uuid4().hex

            for experiment_type in args.experiment:
                print(
                    f"Running {experiment_type} benchmark for {community} "
                    f"(trial {trial_number}/{args.trials_per_community})"
                )
                try:
                    row = run_one_benchmark(
                        dataset_root=args.dataset_root,
                        experiment_type=experiment_type,
                        community=community,
                        model=args.model,
                        max_turns=args.max_turns,
                        run_id=run_id,
                        preserve_trial_output=args.trials_per_community > 1,
                    )
                except Exception as exc:
                    if not is_rate_limit_error(exc):
                        raise
                    raise SystemExit(
                        "OpenAI API returned HTTP 429. Terminating benchmark "
                        "without recording the current experiment run."
                    ) from exc

                append_result(args.csv, row)
                rows_written += 1
                print(f"Appended benchmark row to {args.csv}")
        mark_community_done(community)

        # print("entering NVIDIA NIM downtime...")
        # time.sleep(60)

    print(f"Wrote {rows_written} benchmark row(s) incrementally to {args.csv}")


if __name__ == "__main__":
    main()
