import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PrunedReconstruction.insertions.agent_insert import (
    AgentInsert,
    AgentInsertionTools,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_TTL = (
    PROJECT_ROOT
    / "dataset"
    / "agent"
    / "WayfindingTechnique"
    / "modified_original.ttl"
)


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        content = self.outputs.pop(0)
        usage = SimpleNamespace(
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content)
                )
            ],
            usage=usage,
        )


def valid_plan():
    return {
        "root_class": "WayfindingTechnique",
        "verified_parent": "InteractionTechnique",
        "classes": [
            {
                "class_name": "WayfindingTechnique",
                "parent_class_name": "InteractionTechnique",
                "label": "Wayfinding Technique",
                "comment": "Test reconstruction.",
            }
        ],
        "triples": [],
        "unresolved": [],
    }


class ReconstructionPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.ttl_path = self.temp_dir / "test.ttl"
        self.summary_path = self.temp_dir / "summary.txt"
        shutil.copy2(SOURCE_TTL, self.ttl_path)
        self.summary_path.write_text(
            "WayfindingTechnique is an InteractionTechnique.",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_insertion_requires_an_accepted_plan(self):
        tools = AgentInsertionTools(self.ttl_path)
        with self.assertRaisesRegex(ValueError, "No accepted"):
            tools.insert_class_batch()

    def test_plan_rejects_unknown_relations(self):
        tools = AgentInsertionTools(self.ttl_path)
        plan = valid_plan()
        plan["triples"] = [
            {
                "subject": "WayfindingTechnique",
                "predicate": "UnknownPredicate",
                "object": "UnknownObject",
            }
        ]

        result = tools.submit_reconstruction_plan(**plan)

        self.assertFalse(result["accepted"])
        self.assertEqual(len(result["errors"]), 2)

    def test_agent_commits_accepted_plan_without_extra_model_turn(self):
        plan_json = json.dumps(valid_plan())
        for allow_traversal in (True, False):
            with self.subTest(allow_traversal=allow_traversal):
                ttl_path = self.temp_dir / f"variant-{allow_traversal}.ttl"
                shutil.copy2(SOURCE_TTL, ttl_path)
                outputs = [
                    (
                        "Thought: submit plan\n"
                        "Action: submit_reconstruction_plan\n"
                        f"Action Input: {plan_json}\n"
                        "PAUSE"
                    )
                ]
                agent = AgentInsert(
                    ttl_path,
                    self.summary_path,
                    allow_traversal=allow_traversal,
                )
                agent.client = FakeClient(outputs)

                result = agent.run(max_turns=6, verbose=False)

                self.assertEqual(
                    result,
                    "Inserted 1 classes and 0 grounded triples.",
                )
                self.assertTrue(agent.tools.plan_metrics()["plan_accepted"])
                self.assertEqual(agent.tools.traversal_calls, 0)
                self.assertEqual(agent.total_tokens, 2)

    def test_plan_supports_relations_from_existing_to_new_resources(self):
        summary = (
            "RayCasting supportsTask ReconstructedSelectionTask. "
            "ReconstructedSelectionTask is a subclass of Task."
        )
        self.summary_path.write_text(summary, encoding="utf-8")
        tools = AgentInsertionTools(self.ttl_path, summary=summary)
        plan = valid_plan()
        plan["root_class"] = "ReconstructedSelectionTask"
        plan["verified_parent"] = "Task"
        plan["classes"] = [
            {
                "class_name": "ReconstructedSelectionTask",
                "parent_class_name": "Task",
                "label": "Selection Task",
                "comment": "",
            }
        ]
        plan["triples"] = [
            {
                "subject": "RayCasting",
                "predicate": "supportsTask",
                "object": "ReconstructedSelectionTask",
            }
        ]

        result = tools.submit_reconstruction_plan(**plan)
        insertion = tools.insert_class_batch()

        self.assertTrue(result["accepted"])
        self.assertEqual(result["relation_count"], 1)
        self.assertEqual(insertion["inserted_triple_count"], 1)

    def test_relation_coverage_rejects_silent_omission(self):
        summary = "RayCasting supportsTask SelectionTask."
        tools = AgentInsertionTools(self.ttl_path, summary=summary)
        plan = valid_plan()

        result = tools.submit_reconstruction_plan(**plan)

        self.assertFalse(result["accepted"])
        self.assertTrue(
            any("supportsTask" in error for error in result["errors"])
        )

    def test_exact_summary_literals_override_paraphrases(self):
        summary = """
        ```turtle
        :WayfindingTechnique rdf:type owl:Class ;
            rdfs:label "Wayfinding Technique"@en ;
            rdfs:subClassOf :InteractionTechnique ;
            rdfs:comment "Exact ontology comment."@en .
        ```
        """
        tools = AgentInsertionTools(self.ttl_path, summary=summary)
        plan = valid_plan()
        plan["classes"][0]["label"] = "Paraphrased label"
        plan["classes"][0]["comment"] = "Paraphrased comment"

        result = tools.submit_reconstruction_plan(**plan)

        self.assertTrue(result["accepted"])
        normalized = tools.accepted_plan["classes"][0]
        self.assertEqual(normalized["label"], "Wayfinding Technique")
        self.assertEqual(normalized["comment"], "Exact ontology comment.")


if __name__ == "__main__":
    unittest.main()
