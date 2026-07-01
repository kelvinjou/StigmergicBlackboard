from functools import lru_cache
from pathlib import Path
from textwrap import dedent

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

from config import PROJECT_ROOT, RECONSTRUCTION_PREDICATE_VOCABULARY


BASIC_PREDICATES = {
    RDF.type,
    RDFS.label,
    RDFS.comment,
    RDFS.subClassOf,
}


def _local_name(term):
    text = str(term)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    if "/" in text:
        return text.rstrip("/").rsplit("/", 1)[-1]
    return text


def _english_literal(graph, subject, predicate):
    values = list(graph.objects(subject, predicate))
    if not values:
        return None

    for value in values:
        if isinstance(value, Literal) and str(value.language).lower() == "en":
            return str(value)
    return str(values[0])


def _property_kind(graph, predicate):
    if (predicate, RDF.type, OWL.ObjectProperty) in graph:
        return "ObjectProperty"
    if (predicate, RDF.type, OWL.DatatypeProperty) in graph:
        return "DatatypeProperty"
    if (predicate, RDF.type, OWL.AnnotationProperty) in graph:
        return "AnnotationProperty"
    return "Property"


def _resource_names(graph, subject, predicate):
    return sorted(
        _local_name(value)
        for value in graph.objects(subject, predicate)
        if isinstance(value, URIRef)
    )


@lru_cache(maxsize=8)
def load_predicate_vocabulary(ttl_path=None, min_count=1):
    """Return ontology-local, non-basic predicates used in the source TTL."""

    ttl_path = Path(ttl_path or PROJECT_ROOT / "enhanced_xr.ttl")
    graph = Graph()
    graph.parse(ttl_path, format="ttl")
    default_namespace = dict(graph.namespaces()).get("")
    if default_namespace is None:
        return []

    default_namespace = str(default_namespace)
    predicates = []
    for predicate in sorted(
        {
            pred
            for _subject, pred, _object in graph
            if isinstance(pred, URIRef)
            and str(pred).startswith(default_namespace)
            and pred not in BASIC_PREDICATES
        },
        key=_local_name,
    ):
        count = sum(1 for _ in graph.triples((None, predicate, None)))
        if count < min_count:
            continue

        predicates.append(
            {
                "name": _local_name(predicate),
                "kind": _property_kind(graph, predicate),
                "count": count,
                "label": _english_literal(graph, predicate, RDFS.label),
                "comment": _english_literal(graph, predicate, RDFS.comment),
                "domain": _resource_names(graph, predicate, RDFS.domain),
                "range": _resource_names(graph, predicate, RDFS.range),
            }
        )
    return predicates


def format_predicate_vocabulary(ttl_path=None, min_count=1):
    predicates = (
        load_predicate_vocabulary(ttl_path=ttl_path, min_count=min_count)
        if ttl_path is not None or min_count != 1
        else RECONSTRUCTION_PREDICATE_VOCABULARY
    )
    if not predicates:
        return "Non-basic predicate vocabulary: none discovered."

    lines = [
        "Non-basic predicate vocabulary available for reconstruction:",
        "Use these predicates only when the summary, current ontology, or tool observations provide concrete support.",
    ]
    for item in predicates:
        details = [f":{item['name']}", item["kind"]]
        if "count" in item:
            details.append(f"used {item['count']}x")
        if item["domain"]:
            details.append(f"domain {', '.join(item['domain'])}")
        if item["range"]:
            details.append(f"range {', '.join(item['range'])}")

        description = item.get("description") or item.get("comment") or item.get("label")
        suffix = f" — {description}" if description else ""
        lines.append(f"- {'; '.join(details)}{suffix}")

    return dedent("\n".join(lines)).strip()
