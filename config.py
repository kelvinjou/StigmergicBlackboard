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

# Non-basic ontology predicates that reconstruction experiments may consider.
# These were taken from predicates used at least once in enhanced_xr.ttl,
# excluding basics such as rdf:type, rdfs:label, rdfs:comment, and
# rdfs:subClassOf. Keep this as the shared experiment vocabulary so agent,
# baseline, SPARQL, and summarization prompts stay aligned.
RECONSTRUCTION_PREDICATE_VOCABULARY = (
    {
        "name": "addressesHumanFactor",
        "kind": "ObjectProperty",
        "domain": ("Concept",),
        "range": ("HumanFactor",),
        "description": (
            "Indicates that a concept, technique, or principle is concerned "
            "with a specific human factor."
        ),
    },
    {
        "name": "appliesTo",
        "kind": "ObjectProperty",
        "domain": ("DesignPrinciple",),
        "range": ("Concept",),
        "description": (
            "Links a design principle to the concepts or techniques it guides."
        ),
    },
    {
        "name": "chapterNumber",
        "kind": "DatatypeProperty",
        "domain": ("Chapter",),
        "range": ("integer",),
        "description": "chapter number",
    },
    {
        "name": "coveredInChapter",
        "kind": "ObjectProperty",
        "domain": ("Concept",),
        "range": ("Chapter",),
        "description": (
            "Associates a concept with the textbook chapter in which it is "
            "primarily discussed."
        ),
    },
    {
        "name": "evaluatedBy",
        "kind": "ObjectProperty",
        "domain": ("Concept",),
        "range": ("EvaluationMethod",),
        "description": (
            "Links a concept, technique, or application to the evaluation "
            "methods used to assess it."
        ),
    },
    {
        "name": "isGroundedEvidenceFor",
        "kind": "ObjectProperty",
        "domain": ("GroundedEvidence",),
        "range": ("Concept",),
        "description": (
            "Links a grounded evidence class to the ontology concept it "
            "supports."
        ),
    },
    {
        "name": "supportsTask",
        "kind": "ObjectProperty",
        "domain": ("InteractionTechnique",),
        "range": ("Task",),
        "description": (
            "Links an interaction technique to the task it enables or improves."
        ),
    },
)
