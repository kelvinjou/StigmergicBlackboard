import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace, RDF, RDFS

from PrunedReconstruction.insertions.agent_insert import AgentInsert, AgentInsertionTools
from PrunedReconstruction.insertions.bl_insert import BaselineInsert
from PrunedReconstruction.insertions.sparql_insert import SparQLInsert
from PrunedReconstruction.benchmark_runs import validate_agent_generation


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

    def test_agent_can_search_and_inspect_arbitrary_predicate_patterns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ttl_path = Path(temp_dir) / "ontology.ttl"
            ttl_path.write_text(
                """
                @prefix : <http://example.org/test#> .
                @prefix owl: <http://www.w3.org/2002/07/owl#> .
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

                :InteractionTechnique a owl:Class .
                :SelectionTask a owl:Class ;
                    rdfs:label "Selection Task"@en .
                :TravelTask a owl:Class ;
                    rdfs:label "Travel Task"@en .
                :RayCasting a owl:Class ;
                    rdfs:label "Ray Casting"@en ;
                    rdfs:comment "Pointing technique for selecting targets."@en ;
                    rdfs:subClassOf :InteractionTechnique ;
                    :supportsTask :SelectionTask .
                :Teleportation a owl:Class ;
                    rdfs:subClassOf :InteractionTechnique ;
                    :supportsTask :TravelTask .
                """,
                encoding="utf-8",
            )

            tools = AgentInsertionTools(ttl_path)
            matches = tools.find_resources("ray selecting", limit=5)
            usage = tools.inspect_predicate_usage("supportsTask")
            filtered = tools.inspect_resource(
                "RayCasting", predicate_filter="supportsTask"
            )

            self.assertEqual(matches["matches"][0]["name"], "RayCasting")
            self.assertEqual(usage["predicate"], "supportsTask")
            self.assertEqual(usage["count"], 2)
            self.assertIn(
                {"object": "SelectionTask", "count": 1},
                usage["common_objects"],
            )
            self.assertEqual(
                filtered["outgoing_assertions"][0]["object"],
                "SelectionTask",
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
                self.assertIn("concrete support for the assertion", prompt)
                self.assertIn("Non-basic predicate vocabulary", prompt)
                self.assertIn(":supportsTask", prompt)
                self.assertIn(":coveredInChapter", prompt)

            agent_prompt = AgentInsert(ttl_path, summary_path).messages[0]["content"]
            self.assertIn("inspect_resource", agent_prompt)
            self.assertIn("inspect_predicate_usage", agent_prompt)
            self.assertIn("find_resources", agent_prompt)
            self.assertIn("Non-basic predicate vocabulary", agent_prompt)
            self.assertIn(":supportsTask", agent_prompt)

    def test_agent_stops_after_successful_insert_without_final_llm_turn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ttl_path = Path(temp_dir) / "ontology.ttl"
            summary_path = Path(temp_dir) / "summary.txt"
            ttl_path.write_text(
                """
                @prefix : <http://example.org/test#> .
                @prefix owl: <http://www.w3.org/2002/07/owl#> .
                @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

                :Parent a owl:Class .
                """,
                encoding="utf-8",
            )
            summary_path.write_text("Recover Child under Parent.", encoding="utf-8")
            agent = AgentInsert(ttl_path, summary_path)
            calls = []

            def fake_send_messages(_message):
                calls.append(_message)
                return (
                    "Action: insert_class_batch\n"
                    'Action Input: {"classes": [{"class_name": "Child", '
                    '"parent_class_name": "Parent", "label": "Child", '
                    '"comment": "Recovered child."}], "assertions": []}\n'
                    "PAUSE"
                )

            agent.send_messages = fake_send_messages

            result = agent.run(max_turns=3, verbose=False)

            self.assertEqual(len(calls), 1)
            self.assertIn("inserted_classes=1", result)

    def test_benchmark_flags_agent_runs_without_generated_insertions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_ttl = Path(temp_dir) / "reinserted.ttl"
            output_ttl.write_text(
                "@prefix : <http://example.org/test#> .\n",
                encoding="utf-8",
            )
            paths = {"output_ttl": output_ttl}

            self.assertEqual(
                validate_agent_generation(paths, None),
                "Agent returned no output.",
            )
            self.assertEqual(
                validate_agent_generation(paths, "inserted_classes=1; classes=['A']"),
                "Agent produced no AGENT GENERATION block.",
            )

            output_ttl.write_text(
                "@prefix : <http://example.org/test#> .\n"
                "# AGENT GENERATION (TRAVERSAL + INSERTION TOOLS) OUTPUT\n",
                encoding="utf-8",
            )
            self.assertEqual(
                validate_agent_generation(paths, "inserted_classes=0; classes=[]"),
                "Agent produced an AGENT GENERATION block but inserted zero classes.",
            )


if __name__ == "__main__":
    unittest.main()
