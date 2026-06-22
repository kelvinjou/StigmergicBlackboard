"""Central configuration for reconstruction and query benchmarks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Supported values: "lmstudio" or "nvidia_nim"
# LLM_PROVIDER = "nvidia_nim"
LLM_PROVIDER = "lmstudio"

# Use the model identifier exposed by the selected provider.
# LLM_MODEL = "moonshotai/kimi-k2.6"
LLM_MODEL = "qwen/qwen3.6-35b-a3b"

# Benchmark run configuration.
INPUT_CSV = PROJECT_ROOT / "Ontology_IN.csv"
TRIALS_PER_COMMUNITY = 1
