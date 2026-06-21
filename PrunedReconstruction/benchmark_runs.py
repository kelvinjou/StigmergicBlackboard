# python3 PrunedReconstruction/benchmark_runs.py --all-communities

import argparse
import csv
import hashlib
import json
import os
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

from config import (
    INPUT_CSV,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    NVIDIA_NIM_DOWNTIME,
    TRIALS_PER_COMMUNITY,
)
from PrunedReconstruction.insertions.agent_insert import AgentInsert, DEFAULT_MODEL
from PrunedReconstruction.insertions.bl_insert import BaselineInsert
from PrunedReconstruction.insertions.sparql_insert import SparQLInsert
from PrunedReconstruction.verif_metrics import validate_ttl

EXPERIMENT_TYPES = ("agent", "baseline", "sparql")
# Temporarily disabled because it significantly increases benchmark runtime:
# "agent_no_traversal"
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
    "processed_model_output_path",
    "reconstruction_plan_path",
    "modified_input_sha256",
    "summary_sha256",
    "detached_ground_truth_sha256",
    "elapsed_seconds",
    "ttl_syntax_valid",
    "sparql_query_valid",
    "sparql_insert_only_valid",
    "sparql_operations",
    "execution_success",
    "output_valid",
    "scoring_eligible",
    "failure_type",
    "temperature",
    "top_p",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "plan_submissions",
    "plan_accepted",
    "plan_validation_error_count",
    "plan_warning_count",
    "root_parent_grounded",
    "unresolved_count",
    "traversal_calls",
    "planned_triple_count",
    "inserted_triple_count",
    "grounding_catalog_size",
    "model_calls",
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
    # Every method reads the exact same immutable pruning artifacts. The agent
    # directory is the canonical input location; method directories contain
    # outputs only.
    input_dataset_dir = Path(dataset_root) / "agent" / community
    output_name = f"reinserted_{run_id}.ttl"
    return {
        "dataset_dir": dataset_dir,
        "input_ttl": PROJECT_ROOT / "enhanced_xr.ttl",
        "detached_ttl": input_dataset_dir / "detached.ttl",
        "modified_ttl": input_dataset_dir / "modified_original.ttl",
        "summary": input_dataset_dir / "summary.txt",
        "output_ttl": dataset_dir / output_name,
        "raw_output": dataset_dir / f"raw_model_output_{run_id}.txt",
        "processed_output": (
            dataset_dir / f"generated_output_{run_id}.txt"
        ),
        "plan_output": dataset_dir / f"reconstruction_plan_{run_id}.json",
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
    return "\n".join(prefix_lines + ["", body]).strip()


def validate_sparql_insert_only(query_string):
    try:
        parsed = parseUpdate(query_string)
    except Exception as exc:
        print(f"SPARQL syntax error: {exc}")
        return {
            "syntax_valid": False,
            "insert_only_valid": False,
            "operations": [],
            "error": str(exc),
        }

    operations = [
        getattr(operation, "name", type(operation).__name__)
        for operation in parsed.get("request", [])
    ]
    insert_only_valid = bool(operations) and all(
        operation == "InsertData" for operation in operations
    )
    return {
        "syntax_valid": True,
        "insert_only_valid": insert_only_valid,
        "operations": operations,
        "error": (
            ""
            if insert_only_valid
            else "Only SPARQL INSERT DATA operations are permitted."
        ),
    }


def ensure_dataset_inputs(paths):
    for key in ("modified_ttl", "summary", "detached_ttl"):
        if not paths[key].exists():
            raise FileNotFoundError(f"Missing benchmark input: {paths[key]}")


def token_metrics(insert_runner):
    return {
        "input_tokens": getattr(insert_runner, "prompt_tokens", 0),
        "output_tokens": getattr(insert_runner, "completion_tokens", 0),
        "total_tokens": getattr(insert_runner, "total_tokens", 0),
        "model_calls": getattr(insert_runner, "model_calls", 1),
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_raw_output(paths, output):
    paths["raw_output"].parent.mkdir(parents=True, exist_ok=True)
    paths["raw_output"].write_text(str(output), encoding="utf-8")


def write_processed_output(paths, output):
    paths["processed_output"].parent.mkdir(parents=True, exist_ok=True)
    paths["processed_output"].write_text(str(output), encoding="utf-8")


def write_plan_output(paths, artifact):
    paths["plan_output"].parent.mkdir(parents=True, exist_ok=True)
    paths["plan_output"].write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def run_baseline(paths, model, temperature, top_p):
    ensure_dataset_inputs(paths)
    paths["output_ttl"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["modified_ttl"], paths["output_ttl"])

    baseline = BaselineInsert(
        modified_ttl_path=paths["modified_ttl"],
        summary_file_path=paths["summary"],
        model=model,
        temperature=temperature,
        top_p=top_p,
    )
    raw_output = baseline.send_messages(
        "ONLY OUTPUT THE ADDITIONAL TTL SYNTAX YOU GENERATE BASED ON DESCRIPTIVE SUMMARY PROVIDED IN THE FINAL ANSWER."
    )
    write_raw_output(paths, raw_output)
    additions = extract_md_content(raw_output)
    write_processed_output(paths, additions)

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
        "sparql_insert_only_valid": "",
        "sparql_operations": "",
    }


def run_sparql(paths, model, temperature, top_p):
    ensure_dataset_inputs(paths)
    paths["output_ttl"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["modified_ttl"], paths["output_ttl"])

    sparql_insert = SparQLInsert(
        modified_ttl_path=paths["modified_ttl"],
        summary_file_path=paths["summary"],
        model=model,
        temperature=temperature,
        top_p=top_p,
    )
    raw_output = sparql_insert.send_messages(
        """
        ONLY OUTPUT SPARQL INSERT DATA OPERATIONS BASED ON THE DESCRIPTIVE
        SUMMARY. DELETE, UPDATE, WITH, LOAD, CLEAR, CREATE, DROP, ADD, MOVE,
        COPY, and INSERT/WHERE operations are forbidden.
        Output plain SPARQL only. Do not wrap it in markdown fences.
        """
    )
    write_raw_output(paths, raw_output)
    sparql_output = normalize_sparql_batch(raw_output)
    write_processed_output(paths, sparql_output)
    validation = validate_sparql_insert_only(sparql_output)

    if validation["syntax_valid"] and validation["insert_only_valid"]:
        graph = Graph()
        graph.parse(paths["output_ttl"], format="turtle")
        graph.update(sparql_output)
        graph.serialize(destination=paths["output_ttl"], format="turtle")

    return {
        **token_metrics(sparql_insert),
        "ttl_syntax_valid": validate_ttl(paths["output_ttl"]),
        "sparql_query_valid": validation["syntax_valid"],
        "sparql_insert_only_valid": validation["insert_only_valid"],
        "sparql_operations": "|".join(validation["operations"]),
    }


def run_agent(
    paths,
    model,
    max_turns,
    temperature,
    top_p,
    allow_traversal=True,
):
    ensure_dataset_inputs(paths)
    paths["output_ttl"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["modified_ttl"], paths["output_ttl"])

    agent_insert = AgentInsert(
        modified_ttl_path=paths["output_ttl"],
        summary_file_path=paths["summary"],
        model=model,
        allow_traversal=allow_traversal,
        temperature=temperature,
        top_p=top_p,
    )
    try:
        raw_output = agent_insert.run(max_turns=max_turns)
        write_raw_output(paths, raw_output)
    finally:
        write_plan_output(paths, agent_insert.tools.plan_artifact())

    return {
        **token_metrics(agent_insert),
        **agent_insert.tools.plan_metrics(),
        "ttl_syntax_valid": validate_ttl(paths["output_ttl"]),
        "sparql_query_valid": "",
        "sparql_insert_only_valid": "",
        "sparql_operations": "",
    }


def classify_exception(exc):
    name = type(exc).__name__
    if "Timeout" in name:
        return "api_timeout"
    if name in {
        "APIConnectionError",
        "AuthenticationError",
        "PermissionDeniedError",
        "RateLimitError",
        "NotFoundError",
        "BadRequestError",
        "InternalServerError",
    } or name.endswith("APIError"):
        return "api_error"
    if isinstance(exc, FileNotFoundError):
        return "missing_input"
    return "execution_error"


def should_terminate_for_api_error(exc):
    """Return True for rate limits and API timeout failures.

    Provider SDKs do not always expose the same exception class, so inspect the
    exception chain, class names, HTTP status, and canonical error message.
    """
    current = exc
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        name = type(current).__name__.lower()
        message = str(current).lower()
        status_code = getattr(current, "status_code", None)
        response = getattr(current, "response", None)
        response_status = getattr(response, "status_code", None)

        if (
            "ratelimit" in name
            or "timeout" in name
            or status_code == 429
            or response_status == 429
            or "too many requests" in message
            or "error code: 429" in message
        ):
            return True

        current = current.__cause__ or current.__context__

    return False


def run_one_benchmark(
    dataset_root,
    experiment_type,
    community,
    model,
    max_turns,
    run_id,
    preserve_trial_output=False,
    temperature=LLM_TEMPERATURE,
    top_p=LLM_TOP_P,
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
        "sparql_insert_only_valid": "",
        "sparql_operations": "",
        "plan_submissions": "",
        "plan_accepted": "",
        "plan_validation_error_count": "",
        "plan_warning_count": "",
        "root_parent_grounded": "",
        "unresolved_count": "",
        "traversal_calls": "",
        "planned_triple_count": "",
        "inserted_triple_count": "",
        "grounding_catalog_size": "",
        "model_calls": "",
    }
    error = ""
    failure_type = ""

    start = perf_counter()
    try:
        if experiment_type == "agent":
            metrics.update(
                run_agent(
                    paths,
                    model,
                    max_turns,
                    temperature,
                    top_p,
                )
            )
        elif experiment_type == "agent_no_traversal":
            metrics.update(
                run_agent(
                    paths,
                    model,
                    max_turns,
                    temperature,
                    top_p,
                    allow_traversal=False,
                )
            )
        elif experiment_type == "baseline":
            metrics.update(
                run_baseline(paths, model, temperature, top_p)
            )
        elif experiment_type == "sparql":
            metrics.update(
                run_sparql(paths, model, temperature, top_p)
            )
        else:
            raise ValueError(f"Unsupported experiment type: {experiment_type}")
    except Exception as exc:
        if should_terminate_for_api_error(exc):
            print(
                "Terminating benchmark without logging this attempt: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            raise
        error = f"{type(exc).__name__}: {exc}"
        failure_type = classify_exception(exc)
        print(error)
        traceback.print_exc()
    finally:
        elapsed_seconds = perf_counter() - start

    if not error:
        if not metrics["ttl_syntax_valid"]:
            failure_type = "ttl_syntax_invalid"
        elif (
            experiment_type == "sparql"
            and not metrics["sparql_query_valid"]
        ):
            failure_type = "sparql_syntax_invalid"
        elif (
            experiment_type == "sparql"
            and not metrics["sparql_insert_only_valid"]
        ):
            failure_type = "sparql_policy_violation"
        elif (
            experiment_type in {"agent", "agent_no_traversal"}
            and not metrics["plan_accepted"]
        ):
            failure_type = "agent_plan_not_accepted"

    execution_success = not error
    output_valid = execution_success and not failure_type
    scoring_eligible = output_valid

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
        "processed_model_output_path": (
            str(paths["processed_output"])
            if experiment_type in {"baseline", "sparql"}
            else ""
        ),
        "reconstruction_plan_path": (
            str(paths["plan_output"])
            if experiment_type in {"agent", "agent_no_traversal"}
            else ""
        ),
        "modified_input_sha256": (
            sha256_file(paths["modified_ttl"])
            if paths["modified_ttl"].exists()
            else ""
        ),
        "summary_sha256": (
            sha256_file(paths["summary"])
            if paths["summary"].exists()
            else ""
        ),
        "detached_ground_truth_sha256": (
            sha256_file(paths["detached_ttl"])
            if paths["detached_ttl"].exists()
            else ""
        ),
        "elapsed_seconds": round(elapsed_seconds, 6),
        "ttl_syntax_valid": metrics["ttl_syntax_valid"],
        "sparql_query_valid": metrics["sparql_query_valid"],
        "sparql_insert_only_valid": metrics[
            "sparql_insert_only_valid"
        ],
        "sparql_operations": metrics["sparql_operations"],
        "execution_success": execution_success,
        "output_valid": output_valid,
        "scoring_eligible": scoring_eligible,
        "failure_type": failure_type,
        "temperature": temperature,
        "top_p": top_p,
        "input_tokens": metrics["input_tokens"],
        "output_tokens": metrics["output_tokens"],
        "total_tokens": metrics["total_tokens"],
        "plan_submissions": metrics["plan_submissions"],
        "plan_accepted": metrics["plan_accepted"],
        "plan_validation_error_count": metrics[
            "plan_validation_error_count"
        ],
        "plan_warning_count": metrics["plan_warning_count"],
        "root_parent_grounded": metrics["root_parent_grounded"],
        "unresolved_count": metrics["unresolved_count"],
        "traversal_calls": metrics["traversal_calls"],
        "planned_triple_count": metrics["planned_triple_count"],
        "inserted_triple_count": metrics["inserted_triple_count"],
        "grounding_catalog_size": metrics["grounding_catalog_size"],
        "model_calls": metrics["model_calls"],
        "ground_truth_alignment": "",
        "error": error,
    }


def append_results(csv_path, rows):
    csv_path = Path(csv_path)
    new_df = pd.DataFrame(rows, columns=BENCHMARK_COLUMNS)
    if csv_path.exists():
        existing_df = pd.read_csv(csv_path)
        merged_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        merged_df = new_df
    merged_df.to_csv(csv_path, index=False)
    return csv_path


def append_result(csv_path, row):
    """Durably append one completed benchmark row."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    if not write_header:
        with csv_path.open(newline="", encoding="utf-8") as input_file:
            existing_header = next(csv.reader(input_file), [])
        if existing_header != BENCHMARK_COLUMNS:
            raise ValueError(
                f"Cannot append to {csv_path}: benchmark CSV columns do not "
                "match BENCHMARK_COLUMNS."
            )

    with csv_path.open("a", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=BENCHMARK_COLUMNS,
            extrasaction="ignore",
        )
        if write_header:
            writer.writeheader()
        writer.writerow(
            {column: row.get(column, "") for column in BENCHMARK_COLUMNS}
        )
        output_file.flush()
        os.fsync(output_file.fileno())

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
    parser.add_argument("--temperature", type=float, default=LLM_TEMPERATURE)
    parser.add_argument("--top-p", type=float, default=LLM_TOP_P)
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

    written_rows = 0
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
                row = run_one_benchmark(
                    dataset_root=args.dataset_root,
                    experiment_type=experiment_type,
                    community=community,
                    model=args.model,
                    max_turns=args.max_turns,
                    run_id=run_id,
                    preserve_trial_output=args.trials_per_community > 1,
                    temperature=args.temperature,
                    top_p=args.top_p,
                )
                csv_path = append_result(args.csv, row)
                written_rows += 1
                print(
                    f"Wrote completed benchmark row immediately to {csv_path}"
                )
        mark_community_done(community)

        print(f"entering NVIDIA NIM downtime ({NVIDIA_NIM_DOWNTIME} seconds)...")
        time.sleep(NVIDIA_NIM_DOWNTIME)

    print(f"Wrote {written_rows} benchmark row(s) total to {args.csv}")


if __name__ == "__main__":
    main()
