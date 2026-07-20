"""Consistency-aware repair of LLM-generated SPARQL ontology updates.

The LLM that proposes ontology extensions occasionally emits relations that are
logically inconsistent or ill-formed. This module applies the update to the
ontology graph and then *repairs* it -- keeping every consistent triple and
removing only the offending ones -- entirely locally (no OWL reasoner, no LLM
call). It is domain-agnostic: every rule is derived from the ``owl:disjointWith``
axioms, ``rdfs:domain``/``rdfs:range`` declarations, and class hierarchy that are
present in the loaded graph. Nothing about any particular ontology is hardcoded.

Failure modes handled:

1. Cross-disjoint subsumption -- a class made ``rdfs:subClassOf`` two mutually
   disjoint top-level categories.
2. Domain/range-inferred category clash -- a property whose ``rdfs:domain`` (or
   ``rdfs:range``) would type an entity into a category disjoint with one it
   already belongs to. (A pure OWL-RL reasoner misses this because subClassOf is
   not rdf:type, so the disjointness rule never fires.)
3. Undeclared predicates -- relations using a predicate never declared as an
   ``owl:ObjectProperty``; auto-declared as a bare property (no domain/range, so
   no new inferred-type clash can be introduced) or dropped.
4. Redundant multi-predicate edges -- more than one predicate asserted between
   the same ordered pair; collapsed to a single (preferably declared) predicate.

The core idea that makes repair precise without a reasoner: category membership
is attributed to the specific added triple that grants it, so dropping that one
triple removes exactly that membership.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

# Fallback namespace for auto-declaring new predicates when one cannot be
# inferred from the graph. The real namespace is derived per-graph below.
EX = Namespace("http://example.org/3dui-ontology#")

_BUILTIN_NS = (str(RDF), str(RDFS), str(OWL), str(XSD))


class InconsistentUpdateError(RuntimeError):
    """An update introduces a category clash that could not be repaired away."""


@dataclass
class RepairReport:
    """What ``apply_and_repair`` changed, for surfacing to the caller."""

    dropped: list = field(default_factory=list)        # [(triple, reason)]
    autodeclared: list = field(default_factory=list)   # [predicate URIRef]
    redundant: list = field(default_factory=list)      # [(triple, reason)]
    violations_resolved: list = field(default_factory=list)  # [str]
    kept_added: int = 0

    @property
    def clean(self) -> bool:
        return not (self.dropped or self.redundant)

    def __str__(self) -> str:
        if self.clean and not self.autodeclared:
            return f"consistent update: {self.kept_added} triple(s) written, no repairs"
        lines = [f"update written with repairs ({self.kept_added} triple(s) kept):"]
        for pred in self.autodeclared:
            lines.append(f"  auto-declared predicate: {local_name(pred)}")
        for triple, reason in self.dropped:
            lines.append(f"  dropped {_fmt_triple(triple)} -- {reason}")
        for triple, reason in self.redundant:
            lines.append(f"  dropped {_fmt_triple(triple)} -- {reason}")
        return "\n".join(lines)


def local_name(uri) -> str:
    text = str(uri)
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text


def _fmt_triple(triple) -> str:
    s, p, o = triple
    return f"({local_name(s)} {local_name(p)} {local_name(o)})"


def _is_builtin(uri) -> bool:
    return any(str(uri).startswith(ns) for ns in _BUILTIN_NS)


# --------------------------------------------------------------------------- #
# Read-only graph analysis                                                      #
# --------------------------------------------------------------------------- #

def ontology_namespace(graph: Graph) -> str:
    """Most common namespace among declared classes/properties (for autodeclare)."""
    counts: Counter = Counter()
    declared = (
        set(graph.subjects(RDF.type, OWL.Class))
        | set(graph.subjects(RDF.type, OWL.ObjectProperty))
    )
    for subject in declared:
        if not isinstance(subject, URIRef):
            continue
        text = str(subject)
        for sep in ("#", "/"):
            if sep in text:
                counts[text.rsplit(sep, 1)[0] + sep] += 1
                break
    if counts:
        return counts.most_common(1)[0][0]
    return str(EX)


def categories(graph: Graph) -> set:
    """Classes that participate in any owl:disjointWith axiom (the partitions)."""
    cats: set = set()
    for a, _, b in graph.triples((None, OWL.disjointWith, None)):
        cats.add(a)
        cats.add(b)
    return cats


def disjoint_pairs(graph: Graph) -> set:
    """Normalized unordered disjoint pairs."""
    pairs: set = set()
    for a, _, b in graph.triples((None, OWL.disjointWith, None)):
        if a != b:
            pairs.add(frozenset((a, b)))
    return pairs


def declared_properties(graph: Graph) -> set:
    props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    props |= set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    props |= set(graph.subjects(RDF.type, RDF.Property))
    return props


def class_categories(graph: Graph, cls, cats: set | None = None) -> set:
    """Top-level disjoint categories reachable from ``cls`` via rdfs:subClassOf*."""
    if cats is None:
        cats = categories(graph)
    ancestors = set(graph.transitive_objects(cls, RDFS.subClassOf))
    return ancestors & cats


def _reaches(graph: Graph, node, target) -> bool:
    """True if ``target`` is ``node`` itself or a subClassOf* ancestor of it."""
    return target in graph.transitive_objects(node, RDFS.subClassOf)


def _domain_range_maps(graph: Graph):
    domain: dict = defaultdict(set)
    rng: dict = defaultdict(set)
    for p, _, d in graph.triples((None, RDFS.domain, None)):
        domain[p].add(d)
    for p, _, r in graph.triples((None, RDFS.range, None)):
        rng[p].add(r)
    return domain, rng


def _candidates(added: set) -> set:
    """Entities touched by the added triples that could sit in a category."""
    result: set = set()
    for s, p, o in added:
        if isinstance(s, URIRef):
            result.add(s)
        if isinstance(o, URIRef) and not _is_builtin(p):
            result.add(o)
    return result


def _entity_membership(working, before, entity, cats, added, domain_map, range_map):
    """Categories ``entity`` belongs to, each tagged with whether it is base-derived.

    Subclass memberships come from the full working graph (base + surviving added
    edges); a membership is "base" if it already holds in ``before``. Domain/range
    memberships are inferred only from *added* property triples, so they are never
    base -- they are exactly the new risk this pass exists to catch.
    """
    sc_working = class_categories(working, entity, cats)
    sc_base = class_categories(before, entity, cats)
    membership = set(sc_working)
    cat_base = {cat: (cat in sc_base) for cat in sc_working}

    for s, p, o in added:
        if s == entity:
            for d in domain_map.get(p, ()):
                for cat in class_categories(working, d, cats):
                    membership.add(cat)
                    cat_base.setdefault(cat, False)
        if o == entity:
            for r in range_map.get(p, ()):
                for cat in class_categories(working, r, cats):
                    membership.add(cat)
                    cat_base.setdefault(cat, False)
    return membership, cat_base


def _droppable(working, added, entity, drop_cat, domain_map, range_map) -> set:
    """Added triples whose removal drops ``entity``'s membership in ``drop_cat``."""
    drops: set = set()
    for triple in added:
        s, p, o = triple
        if p == RDFS.subClassOf:
            # Edge s -> o lies on a path entity ->* s -> o ->* drop_cat.
            if _reaches(working, entity, s) and _reaches(working, o, drop_cat):
                drops.add(triple)
        else:
            if s == entity and any(
                _reaches(working, d, drop_cat) for d in domain_map.get(p, ())
            ):
                drops.add(triple)
            if o == entity and any(
                _reaches(working, r, drop_cat) for r in range_map.get(p, ())
            ):
                drops.add(triple)
    return drops


# --------------------------------------------------------------------------- #
# Repair passes                                                                 #
# --------------------------------------------------------------------------- #

def _hygiene_pass(working, added, report, autodeclare, ont_ns):
    """Pass A: ground or drop predicates invented by the LLM."""
    declared = declared_properties(working)
    for triple in list(added):
        _, p, _ = triple
        if _is_builtin(p) or not str(p).startswith(ont_ns) or p in declared:
            continue
        if autodeclare:
            # No domain/range -> cannot introduce a new inferred-type clash.
            working.add((p, RDF.type, OWL.ObjectProperty))
            report.autodeclared.append(p)
            declared.add(p)
        else:
            working.remove(triple)
            added.discard(triple)
            report.dropped.append((triple, "undeclared predicate"))


def _repair_category_clashes(working, before, added, report):
    """Pass B: remove added triples that pull an entity into disjoint categories."""
    cats = categories(working)
    pairs = disjoint_pairs(working)
    if not pairs:
        return

    changed = True
    while changed:
        changed = False
        domain_map, range_map = _domain_range_maps(working)
        for entity in _candidates(added):
            membership, cat_base = _entity_membership(
                working, before, entity, cats, added, domain_map, range_map
            )
            for pair in pairs:
                x, y = tuple(pair)
                if x not in membership or y not in membership:
                    continue
                bx, by = cat_base.get(x, False), cat_base.get(y, False)
                if bx and by:
                    continue  # pre-existing inconsistency: not introduced here
                drop_cat = y if bx else (x if by else max((x, y), key=str))
                drops = _droppable(
                    working, added, entity, drop_cat, domain_map, range_map
                )
                if not drops:
                    continue
                reason = (
                    f"{local_name(entity)} would join disjoint categories "
                    f"{local_name(x)} and {local_name(y)}"
                )
                for triple in drops:
                    working.remove(triple)
                    added.discard(triple)
                    report.dropped.append((triple, reason))
                report.violations_resolved.append(
                    f"{local_name(entity)}: {local_name(x)} vs {local_name(y)}"
                )
                changed = True
                break
            if changed:
                break  # restart scan; the graph changed under us


def _redundancy_pass(working, added, report):
    """Pass C: collapse multiple predicates asserted between the same pair."""
    declared = declared_properties(working)
    by_pair: dict = defaultdict(list)
    for triple in added:
        s, p, o = triple
        if _is_builtin(p) or not (isinstance(s, URIRef) and isinstance(o, URIRef)):
            continue
        by_pair[(s, o)].append(triple)

    for (s, o), triples in by_pair.items():
        preds = {p for _, p, _ in triples}
        if len(preds) <= 1:
            continue
        declared_preds = [p for p in preds if p in declared]
        keep = min(declared_preds, key=str) if declared_preds else min(preds, key=str)
        for triple in triples:
            if triple[1] == keep:
                continue
            if triple in working:
                working.remove(triple)
                added.discard(triple)
                report.redundant.append(
                    (
                        triple,
                        f"collapsed multi-predicate edge {local_name(s)}->"
                        f"{local_name(o)}; kept {local_name(keep)}",
                    )
                )


def _residual_clashes(working, before, added) -> set:
    cats = categories(working)
    pairs = disjoint_pairs(working)
    domain_map, range_map = _domain_range_maps(working)
    residual: set = set()
    for entity in _candidates(added):
        membership, cat_base = _entity_membership(
            working, before, entity, cats, added, domain_map, range_map
        )
        for pair in pairs:
            x, y = tuple(pair)
            if x in membership and y in membership and not (
                cat_base.get(x) and cat_base.get(y)
            ):
                residual.add((entity, pair))
    return residual


# --------------------------------------------------------------------------- #
# Orchestrator                                                                  #
# --------------------------------------------------------------------------- #

def apply_and_repair(
    base_graph: Graph,
    update_command: str,
    *,
    repair: bool = True,
    autodeclare: bool = True,
):
    """Apply ``update_command`` to a copy of ``base_graph`` and repair the result.

    Returns ``(graph, RepairReport)``. ``base_graph`` is never mutated. With
    ``repair=False`` the whole update is rejected (raises
    :class:`InconsistentUpdateError`) if it introduces any new category clash --
    the original all-or-nothing behavior.
    """
    report = RepairReport()

    before = Graph()
    working = Graph()
    for triple in base_graph:
        before.add(triple)
        working.add(triple)
    for prefix, namespace in base_graph.namespaces():
        working.bind(prefix, namespace, replace=True)

    before_set = set(before)
    working.update(update_command)
    added = set(working) - before_set

    if not repair:
        residual = _residual_clashes(working, before, added)
        if residual:
            detail = "; ".join(
                f"{local_name(e)} in disjoint {local_name(tuple(pair)[0])}/"
                f"{local_name(tuple(pair)[1])}"
                for e, pair in sorted(residual, key=str)
            )
            raise InconsistentUpdateError(
                f"Rejected update: introduces category clashes: {detail}"
            )
        report.kept_added = len(added)
        return working, report

    ont_ns = ontology_namespace(working)
    _hygiene_pass(working, added, report, autodeclare, ont_ns)
    _repair_category_clashes(working, before, added, report)
    _redundancy_pass(working, added, report)

    # Pass D: safety net -- if anything slipped through, drop added edges on the
    # offending entities; only raise if that still cannot make it consistent.
    residual = _residual_clashes(working, before, added)
    if residual:
        for entity, _ in residual:
            for triple in list(added):
                if triple[0] == entity or triple[2] == entity:
                    if triple in working:
                        working.remove(triple)
                        added.discard(triple)
                        report.dropped.append(
                            (triple, f"residual-clash safety net for {local_name(entity)}")
                        )
        if _residual_clashes(working, before, added):
            raise InconsistentUpdateError(
                "Could not repair update to a consistent graph."
            )

    report.kept_added = len(added)
    return working, report
