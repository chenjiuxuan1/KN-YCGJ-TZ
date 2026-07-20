import json
import unittest
from datetime import datetime, timedelta, timezone

from governance_automation.ds_dependency_graph import build_dependency_graph
from governance_automation.ds_zombie_classifier import classify_workflow
from governance_automation.ds_zombie_models import EvidenceState, WorkflowSnapshot
from governance_automation.ds_zombie_pipeline import build_summary


class DependencyGraphTests(unittest.TestCase):
    def test_internal_and_cross_workflow_dependencies_are_both_built(self):
        graph = build_dependency_graph(
            relation_rows=[
                {"workflow_code": "w1", "pre_task_code": "t1", "post_task_code": "t2"}
            ],
            task_rows=[
                {
                    "workflow_code": "w2",
                    "task_code": "d1",
                    "task_type": "DEPENDENT",
                    "task_params": json.dumps(
                        {
                            "dependence": {
                                "dependTaskList": [
                                    {
                                        "dependItemList": [
                                            {
                                                "projectCode": "p1",
                                                "definitionCode": "w1",
                                                "depTaskCode": "t2",
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    ),
                }
            ],
        )
        self.assertEqual(graph.task_downstream["w1"]["t1"], {"t2"})
        self.assertEqual(graph.workflow_upstream["w2"], {"w1"})
        self.assertEqual(graph.workflow_downstream["w1"], {"w2"})
        self.assertTrue(graph.scan_complete["w2"])

    def test_malformed_dependent_task_marks_scan_incomplete(self):
        graph = build_dependency_graph(
            relation_rows=[],
            task_rows=[
                {
                    "workflow_code": "w2",
                    "task_code": "d1",
                    "task_type": "DEPENDENT",
                    "task_params": "{",
                }
            ],
        )
        self.assertFalse(graph.scan_complete["w2"])
        self.assertEqual(graph.parse_error_count, 1)


class ZombieClassifierTests(unittest.TestCase):
    def _snapshot(self, **overrides):
        now = datetime.now(timezone.utc)
        values = dict(
            country="th",
            project_code="p1",
            workflow_code="w1",
            project_name="project",
            workflow_name="workflow",
            last_update_time=now - timedelta(days=400),
            last_run_time=now - timedelta(days=400),
            last_success_time=now - timedelta(days=400),
            total_runs_30d=0,
            schedule_online=False,
            instance_scan_complete=True,
            dependency_scan_complete=True,
        )
        values.update(overrides)
        return WorkflowSnapshot(**values)

    def test_stale_unused_complete_workflow_is_a_level_confirmation(self):
        result = classify_workflow(self._snapshot())
        self.assertEqual(result.level, "A")
        self.assertEqual(result.action, "REQUEST_DECOMMISSION_CONFIRMATION")

    def test_downstream_dependency_blocks_decommission(self):
        result = classify_workflow(self._snapshot(downstream_workflows=("w2",)))
        self.assertTrue(result.protected_by_dependency)
        self.assertEqual(result.level, "D")
        self.assertEqual(result.action, "RETAIN_AND_ASSESS")

    def test_unknown_dependency_state_requires_evidence(self):
        result = classify_workflow(self._snapshot(dependency_scan_complete=False))
        self.assertTrue(result.protected_by_uncertainty)
        self.assertEqual(result.level, "C")
        self.assertEqual(result.action, "COLLECT_EVIDENCE")

    def test_recent_activity_is_d_level(self):
        now = datetime.now(timezone.utc)
        result = classify_workflow(
            self._snapshot(last_run_time=now - timedelta(days=2), total_runs_30d=3)
        )
        self.assertEqual(result.level, "D")
        self.assertEqual(result.action, "KEEP_ACTIVE")

    def test_unknown_access_evidence_does_not_become_absent(self):
        result = classify_workflow(
            self._snapshot(access_evidence=EvidenceState.UNKNOWN)
        )
        self.assertIn("访问证据未接入", result.reasons)


class SummaryTests(unittest.TestCase):
    def test_summary_is_bounded_and_has_no_bulk_candidate_field(self):
        candidates = []
        for index in range(50):
            candidates.append(
                {
                    "workflow_code": str(index),
                    "level": "A",
                    "score_total": 80 - index,
                    "protected_by_dependency": index % 2 == 0,
                    "protected_by_uncertainty": False,
                }
            )
        summary = build_summary(
            country="th",
            batch_id="b1",
            score_version="v1",
            scanned_workflows=50,
            candidates=candidates,
            persisted_count=50,
            top_limit=20,
        )
        self.assertEqual(len(summary["top_candidates"]), 20)
        self.assertNotIn("data", summary)
        self.assertNotIn("candidates", summary)
        self.assertEqual(summary["dependency_protected_count"], 25)


if __name__ == "__main__":
    unittest.main()
