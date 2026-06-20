"""Remove generated reinsertion outputs from benchmark dataset directories."""

import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = PROJECT_ROOT / "dataset"
GENERATED_FILE_PATTERNS = (
    "reinserted.ttl",
    "reinserted_*.ttl",
    "raw_model_output_*.txt",
)


def find_generated_files(dataset_root):
    dataset_root = Path(dataset_root).resolve()
    if not dataset_root.is_dir():
        raise NotADirectoryError(f"Dataset directory does not exist: {dataset_root}")

    files = {
        path
        for pattern in GENERATED_FILE_PATTERNS
        for path in dataset_root.rglob(pattern)
        if path.is_file()
    }
    return sorted(files)


def reset_reinsertions(dataset_root=DEFAULT_DATASET_ROOT, dry_run=False):
    dataset_root = Path(dataset_root).resolve()
    generated_files = find_generated_files(dataset_root)

    for path in generated_files:
        print(f"{'Would remove' if dry_run else 'Removing'} {path}")
        if not dry_run:
            path.unlink()

    action = "Found" if dry_run else "Removed"
    print(f"{action} {len(generated_files)} generated reinsertion file(s).")
    return generated_files


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Recursively remove reinserted TTL files and raw model output text "
            "files from benchmark dataset directories."
        )
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help=f"Dataset directory to reset. Defaults to {DEFAULT_DATASET_ROOT}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching files without removing them.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    reset_reinsertions(args.dataset_root, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
