# Stigmergy vs. HNSW-top-k baseline benchmark

This branch (`stigmergy-convergence`) adds a benchmark variant that tests a
specific hypothesis raised by the original schema.org run:

> If HNSW top-k already lands on the right hotspot communities and adjacent
> edges are distinct from the hotspot, the stigmergic walk + pheromone add
> nothing — we could drop the blackboard entirely.

The original benchmark could not test this, because the blackboard is reset per
evidence row, so pheromone (`tau`) never accumulates across evidence, and the
evidence set was topically independent (no shared concept for a trail to
reinforce). This variant fixes both: a concept-clustered evidence set where
trails *can* reinforce, plus a clean top-k-only baseline arm.

## The four arms

All arms share the base ontology, the clustered evidence set, and the HNSW
landing step. They differ only in what happens after landing, and are selected
entirely through `src/config.py` flags. Set `RUN_TAG` to a per-arm directory
name so runs never overwrite each other.

| Arm | RUN_TAG | WALK_ENABLED | PHEROMONE_BIAS_ENABLED | PHEROMONE_BLACKBOARD_PERSISTENCE |
|-----|---------|-------------|------------------------|----------------------------------|
| A0 HNSW-top-k-only (the hypothesis) | `a0_hnsw_only`   | `False` | (n/a) | (n/a) |
| A1 No-pheromone walk                | `a1_no_phero`    | `True`  | `False` | `False` |
| A2 Stigmergy, per-evidence          | `a2_stig_perev`  | `True`  | `True`  | `False` |
| A3 Stigmergy, cross-evidence        | `a3_stig_persist`| `True`  | `True`  | `True`  |

- **A0** skips the trial/step walk entirely and scores + blurbs only the HNSW
  top-k landed communities. If A0 matches A2/A3, the walk and blackboard add
  nothing for this ontology and the hypothesis holds.
- **A3** is the real test of stigmergy: `tau` carries forward across evidence
  rows (`_seed_blackboard_strengths` in `walker.py`), so paraphrases of an
  already-seen concept reinforce the same communities. Blurbs stay per-evidence
  so provenance and SPARQL generation remain keyed to each evidence row.

## Dataset

- `_benchmarks/clustered_summary.txt` — 5 concept clusters of ~4 paraphrases
  each (same underlying fact, varied phrasing) + 1 astronomy negative control.
  One evidence per line; point `config.SUMMARY` at this file.
- `_benchmarks/clustered_gold.csv` — one canonical gold edge per cluster
  (subject / predicate-kind / object) and `expect_edge` (the negative control
  is `no`).

The clusters are designed so a *convergent* system emits ONE shared
relationship edge per cluster, while a system that reinvents predicates mints a
new one per paraphrase (the `causesHypertension` vs `causesHighSodiumDiet` and
`supportsDiabetesManagement` vs `supportsLongTermManagementOfType2Diabetes`
drift already visible in the original CSV).

## Running

Prereqs: LM Studio up with `LMSTUDIO_ENDPOINT` in `.env`; `config.MAIN_ONTOLOGY`
pointing at your local `schema_org.ttl`; `config.SUMMARY` pointing at
`_benchmarks/clustered_summary.txt`. On the first run, uncomment the two
preprocessing calls in `walker.py.__main__` so `_preprocessed/*` and the summary
embeddings are (re)built for the new dataset. The summary-embedding cache is
content-aware and re-embeds automatically when the dataset changes.

For each arm, set its row of flags in `config.py`, then:

```
python walker.py            # answer y at the SPARQL prompt
```

Each arm writes to `_raw_outputs/<RUN_TAG>/` (blackboards `bb*.jsonl`, the
modified ontology, its `.provenance.jsonl` sidecar, and `sparql_logs/`).

LLM blurb/SPARQL generation is non-deterministic; the walk RNG is fixed
(`random.Random(11)`). Consider running each arm 3× and reporting mean ± range.

## Scoring

Pairwise edge diff between any two arms (reuses the existing harness):

```
python -m src.delta_comparisons \
  --w-dir _raw_outputs/a3_stig_persist \
  --no-dir _raw_outputs/a0_hnsw_only \
  --output _raw_outputs/a3_vs_a0_delta.csv
```

Cluster-convergence metrics per arm vs the gold set:

```
python -m src.convergence_metrics                       # every arm found
python -m src.convergence_metrics --arms a0_hnsw_only a3_stig_persist
```

Key metric: **predicate_convergence_ratio** = distinct minted predicates ÷
evidence rows that produced an edge, per cluster. `1/N` (one shared predicate
across N paraphrases) is perfect convergence; `1.0` is full reinvention. Also
reported: gold recall/precision, redundant-edge rate, and hallucinated edges
(the negative control should be 0).

## Interpreting the result

- **A0 ≈ A3** on gold recall AND both converge predicates → HNSW top-k suffices
  for ontologies this simple; stigmergy is optional here. Hypothesis confirmed.
- **A3 shows higher predicate convergence / lower redundancy than A0/A1** on the
  clustered evidence → stigmergy earns its place precisely where evidence
  overlaps; the original benchmark just never exercised it.
