import argparse
import sys
import time
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PrunedReconstruction.benchmark_runs import (
    DEFAULT_MODEL,
    INPUT_CSV,
    append_results,
    read_ontology_csv,
    run_one_benchmark,
)


def communities_from_csv(csv_path):
    df = read_ontology_csv(csv_path)
    return df["communities"].dropna().astype(str).tolist()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rerun SPARQL benchmarks for every community listed in Ontology_IN.csv."
    )
    parser.add_argument("--csv-in", default=INPUT_CSV)
    parser.add_argument("--csv-out", default=PROJECT_ROOT / "benchmark_results1.csv")
    parser.add_argument("--dataset-root", default=PROJECT_ROOT / "dataset")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--sleep-seconds", type=float, default=60)
    return parser.parse_args()


def main():
    args = parse_args()
    run_id = args.run_id or uuid4().hex
    rows = []

    for community in communities_from_csv(args.csv_in):
        print(f"Running sparql benchmark for {community}")
        rows.append(
            run_one_benchmark(
                dataset_root=args.dataset_root,
                experiment_type="sparql",
                community=community,
                model=args.model,
                max_turns=0,
                run_id=run_id,
            )
        )

        if args.sleep_seconds:
            print("entering NVIDIA NIM downtime...")
            time.sleep(args.sleep_seconds)

    csv_path = append_results(args.csv_out, rows)
    print(f"Wrote {len(rows)} SPARQL benchmark row(s) to {csv_path}")


if __name__ == "__main__":
    main()
