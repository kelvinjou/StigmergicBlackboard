"""
Central configuration for the stigmergic walk.

The design separates two quantities that were previously conflated:

    eta (heuristic desirability)  = embedding similarity(evidence, community).
                                    Static, known a-priori, per-evidence.
    tau (pheromone / "strength")  = value deposited on the blackboard.
                                    Learned, accumulated ACROSS evidence and
                                    trials, and evaporated over time.

The walk step samples the next community with probability proportional to
    w(c) = tau(c)^ALPHA * eta(evidence, c)^BETA
which is the Ant System transition rule. This is what makes the system
stigmergic: the trace left on the blackboard (tau) feeds back into future
walks. Set PHEROMONE_BIAS_ENABLED = False to recover the original uniform
random walk (the "no-bias" ablation).
"""

# --- Loop closing -----------------------------------------------------------
# True  -> next step sampled by tau^ALPHA * eta^BETA (stigmergic).
# False -> original fixed-weight strategy + uniform-random node (ablation).
PHEROMONE_BIAS_ENABLED = True

# ACO transition exponents.
ALPHA = 1.0   # pheromone exponent: exploitation of the learned trail (tau).
BETA = 2.0    # heuristic exponent: greediness toward embedding similarity (eta).

# Pheromone initialisation. Candidates with no deposit yet still get TAU_INIT
# so that early walks (empty blackboard) are driven purely by eta instead of
# every weight collapsing to zero.
TAU_INIT = 1.0

# --- Deposit rule -----------------------------------------------------------
# "quality"  -> deposit eta * path_confidence (relevance-weighted).
# "constant" -> deposit CONSTANT_DEPOSIT_Q (visit frequency, evaporated).
DEPOSIT_MODE = "quality"
CONSTANT_DEPOSIT_Q = 1.0

# Diminishing returns for repeated (evidence, community) landings. The n-th
# deposit for the same pair is scaled by DIMINISHING_RETURNS ** (n - 1), so the
# first time we learn "evidence E is relevant to community C" dominates and
# repeated identical hits saturate. Cross-evidence accumulation stays the real
# signal. Set to 1.0 to disable saturation.
DIMINISHING_RETURNS = 0.5

# --- Evaporation ------------------------------------------------------------
# tau <- (1 - EVAPORATION_RATE) * tau, applied once per trial.
EVAPORATION_RATE = 0.05

# --- Blurb gate -------------------------------------------------------------
# eta above this threshold triggers an LLM blurb AND a pheromone deposit, so
# tau marks communities that actually produced enrichment proposals.
BLURB_THRESHOLD = 0.6

# --- Exploration ------------------------------------------------------------
# Even with the bias on, take a random Levy restart with this probability to
# escape local basins.
LEVY_EPSILON = 0.1

# --- Original strategy weights (used only when PHEROMONE_BIAS_ENABLED = False)
TOP_DOWN_WEIGHT = 0.6
ADJACENT_WEIGHT = 0.3
LEVY_WEIGHT = 0.1

# --- Scoring weights (semantic vs structural embedding) ---------------------
SEMANTIC_WEIGHT = 0.85

# --- Path confidence decay per step within a trial --------------------------
PATH_CONFIDENCE_DECAY = 0.9

# --- Generate sparQL iif computed pheromone strength is above x value
# set it to 0.0 for debugging (generate a sparQL for all)
PHEROMONE_SPARQL_GENERATION_MINIMUM = 0.0

NEW_EVIDENCE_PERSISTENCE = True
# PHEROMONE_BLACKBOARD_PERSISTENCE = False