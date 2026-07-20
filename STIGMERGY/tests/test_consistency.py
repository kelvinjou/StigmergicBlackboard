"""Tests for src.consistency.apply_and_repair.

Run in a venv that has rdflib (the default interpreter may not):

    python3 -m venv .venv
    .venv/bin/pip install rdflib==7.6.0 pytest
    .venv/bin/pytest tests/                # or: .venv/bin/python tests/test_consistency.py
"""

from pathlib import Path
import sys

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.consistency import (  # noqa: E402
    InconsistentUpdateError,
    apply_and_repair,
    class_categories,
)

EX = Namespace("http://example.org/3dui-ontology#")
FIXTURE = Path(__file__).parent / "fixtures" / "mini_xr.ttl"

PREFIXES = """
PREFIX : <http://example.org/3dui-ontology#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


def load_base() -> Graph:
    g = Graph()
    g.parse(FIXTURE, format="ttl")
    return g


def run(update_body: str, **kwargs):
    return apply_and_repair(load_base(), PREFIXES + update_body, **kwargs)


def test_cross_disjoint_subsumption_dropped():
    """#1: subClassOf into a category disjoint with an existing one is removed."""
    graph, report = run(
        "INSERT DATA { :PassiveInputDevice rdfs:subClassOf :InteractionTechnique . }"
    )
    bad = (EX.PassiveInputDevice, RDFS.subClassOf, EX.InteractionTechnique)
    assert bad not in graph, "cross-disjoint subClassOf should be dropped"
    # The base parent survives.
    assert (EX.PassiveInputDevice, RDFS.subClassOf, EX.InputDevice) in graph
    assert any(t == bad for t, _ in report.dropped)
    assert EX.InteractionTechnique not in class_categories(graph, EX.PassiveInputDevice)


def test_domain_range_inferred_clash_dropped():
    """#2: the :usesHardware domain trap (owlrl would miss this) is removed."""
    graph, report = run(
        "INSERT DATA { :PassiveInputDevice :usesHardware :OpticalTracker . }"
    )
    bad = (EX.PassiveInputDevice, EX.usesHardware, EX.OpticalTracker)
    assert bad not in graph, "domain-inferred category clash should be dropped"
    assert any(t == bad for t, _ in report.dropped)
    assert EX.InteractionTechnique not in class_categories(graph, EX.PassiveInputDevice)


def test_undeclared_predicate_autodeclared():
    """#3: an invented predicate is auto-declared (bare) and its edge kept."""
    graph, report = run(
        "INSERT DATA { :PassiveInputDevice :supports :TravelTechnique . }"
    )
    edge = (EX.PassiveInputDevice, EX.supports, EX.TravelTechnique)
    assert edge in graph, "meaningful cross-category edge should be kept"
    assert (EX.supports, RDF.type, OWL.ObjectProperty) in graph
    assert EX.supports in report.autodeclared
    # Bare declaration: no domain/range that could re-introduce a clash.
    assert not list(graph.objects(EX.supports, RDFS.domain))
    assert not list(graph.objects(EX.supports, RDFS.range))


def test_undeclared_predicate_dropped_when_autodeclare_off():
    graph, report = run(
        "INSERT DATA { :PassiveInputDevice :supports :TravelTechnique . }",
        autodeclare=False,
    )
    edge = (EX.PassiveInputDevice, EX.supports, EX.TravelTechnique)
    assert edge not in graph
    assert any(t == edge for t, _ in report.dropped)


def test_redundant_multi_predicate_collapsed():
    """#4: two predicates on the same ordered pair collapse to one."""
    graph, report = run(
        "INSERT DATA { :PassiveInputDevice :requires :OpticalTracker ; "
        ":supports :OpticalTracker . }"
    )
    remaining = [
        p
        for p in graph.predicates(EX.PassiveInputDevice, EX.OpticalTracker)
    ]
    assert len(remaining) == 1, f"expected one predicate, got {remaining}"
    assert report.redundant, "collapse should be reported"


def test_happy_path_untouched():
    graph, report = run(
        "INSERT DATA { "
        ":CyberSickness a owl:Class ; rdfs:subClassOf :HumanFactor . "
        ":TravelTechnique :causes :CyberSickness . }"
    )
    assert (EX.CyberSickness, RDFS.subClassOf, EX.HumanFactor) in graph
    assert (EX.TravelTechnique, EX.causes, EX.CyberSickness) in graph
    assert report.clean, f"happy path should need no repair, got: {report}"


def test_base_graph_not_mutated():
    base = load_base()
    before = set(base)
    apply_and_repair(
        base,
        PREFIXES + "INSERT DATA { :PassiveInputDevice rdfs:subClassOf :InteractionTechnique . }",
    )
    assert set(base) == before, "apply_and_repair must not mutate the base graph"


def test_reject_mode_raises():
    raised = False
    try:
        run(
            "INSERT DATA { :PassiveInputDevice rdfs:subClassOf :InteractionTechnique . }",
            repair=False,
        )
    except InconsistentUpdateError:
        raised = True
    assert raised, "repair=False must raise on a new category clash"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
