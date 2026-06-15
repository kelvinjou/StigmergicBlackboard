"""
take in csv containing search queries, provide path too

run query baseline and query agent, add the results to the same row (token usage, time, etc.)
write each result to a txt file. CSV should have path to the txt file
"""

import pandas as pd
import os
import time
import uuid
from datetime import datetime, timezone

if __package__:
    from .q_agent import QueryAgent
    from .q_bl import QueryBaseline
else:
    from q_agent import QueryAgent
    from q_bl import QueryBaseline

def _log_output(folder_name, file_name, content):
    full_path = os.path.join(folder_name, file_name)
    os.makedirs(folder_name, exist_ok=True)

    with open(full_path, "w") as f:
        f.write(content or "")

    return full_path

def _result_row(run_id, run_timestamp, query_id, query, method, output_path, elapsed_seconds, runner):
    return {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "query_in_row_id": query_id,
        "query": query,
        "method": method,
        "output_file_path": output_path,
        "elapsed_seconds": elapsed_seconds,
        "prompt_tokens": runner.prompt_tokens,
        "completion_tokens": runner.completion_tokens,
        "total_tokens": runner.total_tokens,
    }

df = pd.read_csv("QueryBench/query_in.csv")
run_id = str(uuid.uuid1())
run_timestamp = datetime.now(timezone.utc).isoformat()
results = []

for row in df.itertuples(index=False):
    query_id = row.id
    q = row.query
    
    qa = QueryAgent()
    start = time.perf_counter()
    agent_answer = qa.query(q)
    agent_elapsed = time.perf_counter() - start
    agent_output_path = _log_output(
        "QueryBench/outputs",
        f"{run_id}_{query_id}_agent.txt",
        agent_answer,
    )
    results.append(
        _result_row(
            run_id,
            run_timestamp,
            query_id,
            q,
            "agent",
            agent_output_path,
            agent_elapsed,
            qa,
        )
    )

    qb = QueryBaseline()
    start = time.perf_counter()
    bl_answer = qb.send_messages(q)
    bl_elapsed = time.perf_counter() - start
    bl_output_path = _log_output(
        "QueryBench/outputs",
        f"{run_id}_{query_id}_baseline.txt",
        bl_answer,
    )
    results.append(
        _result_row(
            run_id,
            run_timestamp,
            query_id,
            q,
            "baseline",
            bl_output_path,
            bl_elapsed,
            qb,
        )
    )

results_path = "QueryBench/query_bench_results.csv"
results_df = pd.DataFrame(results)
results_df.to_csv(
    results_path,
    mode="a",
    header=not os.path.exists(results_path),
    index=False,
)
