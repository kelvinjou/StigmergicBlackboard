import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS

from PrunedReconstruction.insertions.agent_insert import AgentInsertionTools
from PrunedReconstruction.insertions.bl_insert import BaselineInsert
from PrunedReconstruction.insertions.sparql_insert import SparQLInsert
from PrunedReconstruction.pruning.baseline_summarization import (
    build_explicit_assertion_inventory,
)


EX = Namespace("http://example.org/test#")


class PredicateCapableInsertionTests(unittest.TestCase):
    def test_agent_inserts_outgoing_incoming_and_literal_assertions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ttl_path = Path(temp_dir) / "ontology.ttl"
            ttl_path.write_text(
                """
                @prefix : <http://example.org/test#> .
                @prefix owl: <http://www.w3.org/2002/07/owl#> .
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

                :Concept a owl:Class .
                :ExistingParent a owl:Class ;
                    rdfs:subClassOf :Concept .
                :ExistingTask a owl:Class ;
                    rdfs:subClassOf :Concept .
                :ExistingSource a owl:Class ;
                    rdfs:subClassOf :Concept .
                :supportsTask a owl:ObjectProperty .
                :references a owl:ObjectProperty .
                :confidence a owl:DatatypeProperty .
                """,
                encoding="utf-8",
            )

            tools = AgentInsertionTools(ttl_path)
            result = tools.insert_class_batch(
                classes=[
                    {
                        "class_name": "RecoveredClass",
                        "parent_class_name": "ExistingParent",
                        "label": "Recovered Class",
                        "comment": "Recovered from a summary.",
                        "relations": [
                            {
                                "predicate": "supportsTask",
                                "object": "ExistingTask",
                            }
                        ],
                    }
                ],
                assertions=[
                    {
                        "subject": "ExistingSource",
                        "predicate": "references",
                        "object": "RecoveredClass",
                        "object_type": "uri",
                    },
                    {
                        "subject": "RecoveredClass",
                        "predicate": "confidence",
                        "object": "high",
                        "object_type": "literal",
                        "language": "en",
                    },
                ],
            )

            graph = Graph().parse(ttl_path, format="ttl")
            self.assertIn(
                (EX.RecoveredClass, RDFS.subClassOf, EX.ExistingParent),
                graph,
            )
            self.assertIn(
                (EX.RecoveredClass, EX.supportsTask, EX.ExistingTask),
                graph,
            )
            self.assertIn(
                (EX.ExistingSource, EX.references, EX.RecoveredClass),
                graph,
            )
            self.assertIn(
                (
                    EX.RecoveredClass,
                    EX.confidence,
                    Literal("high", lang="en"),
                ),
                graph,
            )
            self.assertEqual(result["inserted_count"], 1)
            self.assertEqual(result["inserted_assertion_count"], 2)

    def test_agent_inspection_exposes_non_hierarchical_edges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ttl_path = Path(temp_dir) / "ontology.ttl"
            ttl_path.write_text(
                """
                @prefix : <http://example.org/test#> .
                @prefix owl: <http://www.w3.org/2002/07/owl#> .

                :Target a owl:Class ;
                    :supportsTask :Task .
                :Source :references :Target .
                :Task a owl:Class .
                """,
                encoding="utf-8",
            )

            details = AgentInsertionTools(ttl_path).inspect_class("Target")

            self.assertEqual(
                details["outgoing_assertions"][0]["predicate"],
                "supportsTask",
            )
            self.assertEqual(
                details["incoming_assertions"][0]["predicate"],
                "references",
            )

    def test_all_prompts_require_non_hierarchical_reconstruction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ttl_path = Path(temp_dir) / "ontology.ttl"
            summary_path = Path(temp_dir) / "summary.txt"
            ttl_path.write_text(
                "@prefix : <http://example.org/test#> .\n",
                encoding="utf-8",
            )
            summary_path.write_text("Explicit relationship summary.", encoding="utf-8")

            baseline_prompt = BaselineInsert(
                ttl_path, summary_path
            ).messages[0]["content"]
            sparql_prompt = SparQLInsert(
                ttl_path, summary_path
            ).messages[0]["content"]

            for prompt in (baseline_prompt, sparql_prompt):
                self.assertIn("non-hierarchical predicates", prompt)
                self.assertIn("assertions from retained resources", prompt)

    def test_summary_inventory_preserves_exact_non_hierarchical_triples(self):
        graph = Graph()
        graph.bind("", EX)
        graph.add((EX.Child, RDFS.subClassOf, EX.Parent))
        graph.add((EX.Child, EX.supportsTask, EX.Task))
        graph.add((EX.Source, EX.references, EX.Child))
        graph.add((EX.Child, RDF.type, EX.CustomType))

        inventory = build_explicit_assertion_inventory(graph)

        self.assertIn(":Child :supportsTask :Task", inventory)
        self.assertIn(":Source :references :Child", inventory)
        self.assertIn(":Child rdf:type :CustomType", inventory)
        self.assertNotIn("subClassOf", inventory)


if __name__ == "__main__":
    unittest.main()
