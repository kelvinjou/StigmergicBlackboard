# Verification Metrics
import runpy
import sys
from inspect import isclass, ismodule
from time import perf_counter

from rdflib import Graph
from rdflib.plugins.parsers.notation3 import BadSyntax

# check for TTL syntax errors
def validate_ttl(file_path):
    g = Graph()
    try:
        g.parse(file_path, format="ttl")
        print(f"TTL Syntax OK ✅")
        return True
    except BadSyntax as e:
        print(f"Error: bad syntax - {e}")
        return False
    except Exception as e:
        print(f"An unknown error occurred - {e}")
        return False

# execution time (for reinsertion ONLY)
def total_time_taken(script_path):
    """
    Execute a Python script and return runtime and token metrics.

    Example:
        metrics = total_time_taken("PrunedReconstruction/insertions/insert_into_mod.py")
        print(metrics["elapsed_seconds"])
        print(metrics["tokens"])
    """
    start = perf_counter()
    namespace = {}
    try:
        namespace = runpy.run_path(script_path, run_name="__main__")
    finally:
        elapsed = perf_counter() - start
        print(f"{script_path} took {elapsed:.4f} seconds")

    tokens = total_token_consumption(namespace)
    print_token_consumption(tokens)
    return {
        "elapsed_seconds": elapsed,
        "tokens": tokens,
    }

# token consumption (for reinsertion ONLY)
def total_token_consumption(namespace):
    """
    Sum token usage from objects in a completed script namespace.

    This works with objects like BaselineInsert because they store:
        prompt_tokens
        completion_tokens
        total_tokens
    """
    tokens = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    for value in namespace.values():
        if isclass(value) or ismodule(value):
            continue

        if not all(hasattr(value, attr) for attr in ("prompt_tokens", "completion_tokens", "total_tokens")):
            continue

        tokens["input_tokens"] += value.prompt_tokens
        tokens["output_tokens"] += value.completion_tokens
        tokens["total_tokens"] += value.total_tokens

    return tokens


def print_token_consumption(tokens):
    print(
        "Token usage: "
        f"input={tokens['input_tokens']}, "
        f"output={tokens['output_tokens']}, "
        f"total={tokens['total_tokens']}"
    )

# "Pruned Loss Reconstruction" is the measure of how similar the text-to-graph step 
# in the insert task is from the actual graph cut out from the ground truth


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 PrunedReconstruction/verif_metrics.py <script_path>")
        raise SystemExit(1)

    total_time_taken(sys.argv[1])


# run script with: Python3 PrunedReconstruction/verif_metrics.py PrunedReconstruction/insertions/sparql_insert_execute.py
