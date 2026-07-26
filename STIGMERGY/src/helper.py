from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from time import perf_counter

from rdflib import Graph
from rdflib.namespace import OWL, RDFS
from pyparsing import ParseException

from src import config
from src.config import NEW_EVIDENCE_PERSISTENCE, PHEROMONE_SPARQL_GENERATION_MINIMUM
from src.preprocessing import MAIN_ONTOLOGY

SPARQL_FENCE_PATTERN = re.compile(r"(?is)```sparql\s*(.*?)\s*```")
PREFIX_PATTERN = re.compile(r"(?im)^\s*PREFIX\s+\w+:\s*<[^>]+>\s*$")
INSERT_PATTERN = re.compile(r"(?i)INSERT\s+DATA\s*\{")
UPDATE_OPERATION_PATTERN = re.compile(
    r"(?i)\b(?:INSERT\s+DATA|DELETE|DROP|CLEAR|LOAD|CREATE|MOVE|COPY|ADD|WITH|USING|SERVICE)\b"
)
CONFIGURED_CURIE_IN_ANGLE_PATTERN = re.compile(
    rf"<({re.escape(config.ONTOLOGY_NAMESPACE_PREFIX)}:[^>]+)>"
)
BLACKBOARD_EVIDENCE_ROW_PATTERN = re.compile(r"bb(\d+)\.jsonl$")


class InconsistentUpdateError(RuntimeError):
    """A SPARQL update would place a class under two owl:disjointWith branches."""


class SparqlExtractionError(ValueError):
    """Raised when an LLM response cannot be reduced to one safe INSERT DATA update."""


class InvalidSparqlUpdateError(RuntimeError):
    """A generated SPARQL update was malformed or outside the accepted subset."""


def _load_blackboard_items(blackboard_path):
    if not blackboard_path.exists():
        blackboard_path.parent.mkdir(parents=True, exist_ok=True)
        blackboard_path.touch()
        return {}

    items = {}
    with blackboard_path.open("r", encoding="utf8") as blackboard:
        for line in blackboard:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            items[item["community_id"]] = item
    return items


def _write_blackboard_items(blackboard_path, items):
    blackboard_path.parent.mkdir(parents=True, exist_ok=True)
    with blackboard_path.open("w", encoding="utf8") as blackboard:
        for item in items.values():
            blackboard.write(json.dumps(item) + "\n")


def _timestamped_sparql_log_path(log_dir=None) -> Path:
    if log_dir is None:
        log_dir = Path("_raw_outputs/sparql_logs")
    log_dir = Path(log_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return log_dir / f"{timestamp}.txt"


def _initialize_sparql_log(log_dir=None) -> Path:
    log_path = _timestamped_sparql_log_path(log_dir=log_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    config_path = Path(config.__file__)
    with log_path.open("w", encoding="utf8") as log:
        log.write(f"Generated at: {datetime.now().isoformat(timespec='seconds')}\n")
        log.write(f"Config path: {config_path}\n\n")
        log.write("config.py:\n")
        log.write("```python\n")
        log.write(config_path.read_text(encoding="utf8").strip())
        log.write("\n```\n\n")
        log.write("SPARQL commands:\n\n")
    return log_path


def _evidence_row_from_blackboard_path(blackboard_path) -> str:
    match = BLACKBOARD_EVIDENCE_ROW_PATTERN.fullmatch(Path(blackboard_path).name)
    if match:
        return match.group(1)
    return "unknown"


def _log_sparql_command(log_path, blackboard_path, command):
    """Append one generated SPARQL command under the evidence row that produced it."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_row = _evidence_row_from_blackboard_path(blackboard_path)
    with log_path.open("a", encoding="utf8") as log:
        log.write(f"Evidence row: {evidence_row}\n")
        log.write(f"Blackboard: {blackboard_path}\n")
        log.write("SPARQL command:\n")
        log.write(command.strip())
        log.write("\n\n---\n\n")


def _local_name(uri) -> str:
    text = str(uri)
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text


def _disjointness_violations(graph: Graph) -> set[tuple]:
    """Classes that are transitively rdfs:subClassOf two owl:disjointWith branches.

    This is the exact inconsistency Option 2 introduced (a device made a subclass
    of both HardwareComponent and the disjoint InteractionTechnique). It is a
    pure traversal of the already-parsed graph -- no OWL reasoner and no LLM
    call -- so it adds no network latency. Returns (class, branch_a, branch_b)
    with the branch pair order-normalized so mirror declarations collapse.
    """
    violations: set[tuple] = set()
    for branch_a, _, branch_b in graph.triples((None, OWL.disjointWith, None)):
        subs_a = set(graph.transitive_subjects(RDFS.subClassOf, branch_a))
        subs_b = set(graph.transitive_subjects(RDFS.subClassOf, branch_b))
        low, high = sorted((branch_a, branch_b), key=str)
        for clash in subs_a & subs_b:
            violations.add((clash, low, high))
    return violations


def _extract_sparql_update(response: str) -> str:
    fence_match = SPARQL_FENCE_PATTERN.search(response)
    if fence_match:
        response = fence_match.group(1)

    # Always include the configured prefixes because the LLM sometimes omits
    # one while still using the CURIE in the INSERT block.
    prefixes = [
        *config.sparql_prefix_lines(),
        *(match.group(0).strip() for match in PREFIX_PATTERN.finditer(response)),
    ]
    insert_block = _extract_insert_data_block(response)
    if not insert_block:
        return "INSERT DATA { }"

    sparql = "\n".join([*dict.fromkeys(prefixes), "", insert_block]).strip()
    return CONFIGURED_CURIE_IN_ANGLE_PATTERN.sub(r"\1", sparql)


def _extract_insert_data_block(text: str) -> str | None:
    candidates = []
    # Brace matching must ignore literal text. Otherwise a comment like
    # "contains }" can make us truncate the INSERT block before rdflib sees it.
    masked_text = _mask_sparql_strings_and_comments(text)

    # Only accept top-level INSERT DATA blocks. A common bad response is an
    # INSERT nested inside another malformed INSERT, which rdflib reports as
    # "Expected end of text, found 'INSERT'".
    depths = _brace_depths(masked_text)

    for match in INSERT_PATTERN.finditer(masked_text):
        if depths[match.start()] != 0:
            continue
        block = _extract_balanced_block(text, masked_text, match)
        if block is None:
            continue
        if _contains_nested_or_forbidden_update(block):
            continue
        candidates.append(block)

    if not candidates:
        # If the model tried to emit SPARQL but every block was malformed, fail
        # loudly so the caller can skip this blackboard item without writing.
        if INSERT_PATTERN.search(masked_text):
            raise SparqlExtractionError(
                "LLM response contains INSERT DATA, but no single safe balanced block."
            )
        return None

    return candidates[0]


def _brace_depths(masked_text: str) -> list[int]:
    """Return the brace nesting depth before each character in masked SPARQL."""
    depths = []
    depth = 0
    for char in masked_text:
        depths.append(depth)
        if char == "{":
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
    return depths


def _extract_balanced_block(text: str, masked_text: str, match: re.Match) -> str | None:
    """Extract exactly one INSERT DATA block by balancing braces."""
    start = match.start()
    brace_start = masked_text.find("{", match.end() - 1)
    if brace_start == -1:
        return None

    depth = 0
    for index in range(brace_start, len(masked_text)):
        char = masked_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1].strip()
    return None


def _contains_nested_or_forbidden_update(block: str) -> bool:
    # The executor intentionally accepts only one INSERT DATA operation. Anything
    # else is either invalid for this pipeline or too broad to trust from the LLM.
    masked_block = _mask_sparql_strings_and_comments(block)
    body_start = masked_block.find("{")
    body = masked_block[body_start + 1:] if body_start != -1 else masked_block
    return UPDATE_OPERATION_PATTERN.search(body) is not None


def _mask_sparql_strings_and_comments(text: str) -> str:
    """Blank strings/comments while preserving indexes for brace matching."""
    chars = list(text)
    index = 0
    quote = None
    triple_quote = False

    while index < len(chars):
        char = chars[index]

        if quote is None and char == "#":
            while index < len(chars) and chars[index] != "\n":
                chars[index] = " "
                index += 1
            continue

        if quote is None and char in ("'", '"'):
            quote = char
            triple_quote = text[index:index + 3] == char * 3
            stop = index + 3 if triple_quote else index + 1
            for mask_index in range(index, min(stop, len(chars))):
                chars[mask_index] = " "
            index = stop
            continue

        if quote is not None:
            if char == "\\":
                chars[index] = " "
                if index + 1 < len(chars):
                    chars[index + 1] = " "
                index += 2
                continue

            if triple_quote and text[index:index + 3] == quote * 3:
                for mask_index in range(index, min(index + 3, len(chars))):
                    chars[mask_index] = " "
                index += 3
                quote = None
                triple_quote = False
                continue

            if not triple_quote and char == quote:
                chars[index] = " "
                index += 1
                quote = None
                continue

            if char != "\n":
                chars[index] = " "
            index += 1
            continue

        index += 1

    return "".join(chars)


def _execute_sparQL_command(
    ttl_path,
    command,
    output_path=None,
):
    g = Graph()
    if output_path is None:
        output_path = config.OUTPUT_ONTOLOGY
    output_path = Path(output_path)

    if NEW_EVIDENCE_PERSISTENCE and output_path.exists():
        g.parse(output_path, format=config.ONTOLOGY_FORMAT)
        # update community embedding and also HNSW 

    else:
        g.parse(ttl_path, format=config.ONTOLOGY_FORMAT)
    # Snapshot pre-existing violations so the guard only rejects NEW ones the
    # update introduces, never inconsistencies already baked into the ontology.
    before = _disjointness_violations(g)
    try:
        command = _extract_sparql_update(command)
        g.update(command)
    except (SparqlExtractionError, ParseException) as error:
        raise InvalidSparqlUpdateError(f"Rejected malformed SPARQL update: {error}") from error

    introduced = _disjointness_violations(g) - before
    if introduced:
        detail = "; ".join(
            f"{_local_name(c)} would be subClassOf both "
            f"{_local_name(a)} and {_local_name(b)} (disjoint)"
            for c, a, b in sorted(introduced, key=str)
        )
        raise InconsistentUpdateError(
            f"Rejected SPARQL update; not written to {output_path}. "
            f"It introduces disjointness violations: {detail}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)


    g.serialize(destination=output_path, format="ttl")
    return output_path

def _generate_sparQL(blackboard_path=None):
    from src.generate_sparQL import (
        blackboard_paths,
        retrieve_blurbs,
        strongest_communities,
    )

    user_input = input("Generate hypothesis and proposed relations? (y/n): ")
    user_input = user_input.strip().lower()

    if user_input == "y":
        paths = blackboard_paths(blackboard_path)
        if not paths:
            print("No blackboard files found; skipping SPARQL generation.")
            return

        generated_count = 0
        sparql_log_path = _initialize_sparql_log()
        print(f"Logging generated SPARQL commands to {sparql_log_path}")
        for path in paths:
            communities = strongest_communities(
                minimum=PHEROMONE_SPARQL_GENERATION_MINIMUM,
                k=3,
                blackboard_path=path,
            )
            if not communities:
                print(f"No qualifying communities in {path}; skipping.")
                continue

            print(f"Generating SPARQL from {path}")
            try:
                sparql_command = retrieve_blurbs(communities=communities)
            except SparqlExtractionError as error:
                print(f"SPARQL extraction failed for {path}; skipping:\n {error}")
                continue
            _log_sparql_command(
                log_path=sparql_log_path,
                blackboard_path=path,
                command=sparql_command,
            )
            try:
                _execute_sparQL_command(
                    ttl_path=str(MAIN_ONTOLOGY), # run the sparQL command on the original ontology we preprocessed
                    command=sparql_command
                )
            except InconsistentUpdateError as error:
                print(f"SPARQL update rejected for {path} (ontology left unchanged):\n {error}")
                print(f"Offending SPARQL:\n {sparql_command}")
                continue
            except InvalidSparqlUpdateError as error:
                print(f"SPARQL update malformed for {path} (ontology left unchanged):\n {error}")
                print(f"Offending SPARQL:\n {sparql_command}")
                continue

            generated_count += 1
            print(f"SPARQL commands from {path}:\n {sparql_command}")

        if generated_count == 0:
            print("No SPARQL commands were generated.")

    elif user_input == "n":
        raise SystemExit(0)
    else:
        raise RuntimeError("Please enter 'y' or 'n'.")
    
def _new_evidence_ontology_persistence():
    # each run should use its own summary.txt, enhanced_xr.ttl
    # for each run, create a copy of the embedding if it doesn't exist yet
    # add the new embedding to pkl, add the new HNSW
    # do not persist blackboard across different evidence rows (the scores correspond to different evidence)
    pass
    
@contextmanager
def timed_stage(name: str):
    start = perf_counter()
    try:
        yield
    finally:
        elapsed = perf_counter() - start
        print(f"{name} finished in {elapsed:.2f}s")

if __name__ == "__main__":
    _execute_sparQL_command(
        ttl_path=config.MAIN_ONTOLOGY,
        command=f"""
            {config.prompt_template_values()["SPARQL_PREFIX_LINES"]}

            INSERT DATA {{ }}
        """,
    )
