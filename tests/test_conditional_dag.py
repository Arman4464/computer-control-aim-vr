"""
Unit tests for Conditional Action DAG Engine.
Verifies pre-conditions, post-conditions, dynamic branching (if_true/if_false),
error recovery branches, and variable resolution using mock tool dispatchers.
"""

import unittest
from control.dag_executor import DAGExecutor


class TestConditionalDAG(unittest.TestCase):

    def test_condition_evaluation_primitives(self):
        executor = DAGExecutor()
        context = {
            "steps": {
                "s1": {"result": {"status": "ok", "count": 5, "title": "Chrome"}}
            }
        }

        # equals
        sat, _ = executor.evaluate_condition({"type": "equals", "left": "{{steps.s1.result.status}}", "right": "ok"}, context)
        self.assertTrue(sat)

        sat, _ = executor.evaluate_condition({"type": "equals", "left": "{{steps.s1.result.status}}", "right": "error"}, context)
        self.assertFalse(sat)

        # contains
        sat, _ = executor.evaluate_condition({"type": "contains", "left": "{{steps.s1.result.title}}", "right": "chrom"}, context)
        self.assertTrue(sat)

        # not_equals
        sat, _ = executor.evaluate_condition({"type": "not_equals", "left": "{{steps.s1.result.count}}", "right": "0"}, context)
        self.assertTrue(sat)

    def test_pre_condition_skip_and_branch(self):
        executed = []

        def mock_dispatcher(action, args):
            executed.append(action)
            return {"status": "done"}, False

        executor = DAGExecutor(tool_dispatcher=mock_dispatcher)

        # Step 1 sets variable
        # Step 2 has pre_condition that fails -> branches to Step 3
        steps = [
            {
                "id": "step_init",
                "action": "action_init",
                "args": {},
            },
            {
                "id": "step_guarded",
                "action": "action_guarded",
                "pre_condition": {"type": "equals", "left": "val_a", "right": "val_b"},  # Fails!
                "on_condition_failed": "step_fallback",
            },
            {
                "id": "step_normal",
                "action": "action_normal",
            },
            {
                "id": "step_fallback",
                "action": "action_fallback",
            }
        ]

        res = executor.run_dag(steps, stop_on_error=True)
        self.assertEqual(res["status"], "success")
        # Step 2 should not execute its action, it should branch to step_fallback
        self.assertIn("action_init", executed)
        self.assertNotIn("action_guarded", executed)
        self.assertIn("action_fallback", executed)

    def test_success_branching(self):
        executed = []

        def mock_dispatcher(action, args):
            executed.append(action)
            return {"status": "done"}, False

        executor = DAGExecutor(tool_dispatcher=mock_dispatcher)

        steps = [
            {
                "id": "s1",
                "action": "action_1",
                "on_success": "s3",  # Skip s2!
            },
            {
                "id": "s2",
                "action": "action_2",
            },
            {
                "id": "s3",
                "action": "action_3",
            }
        ]

        res = executor.run_dag(steps)
        self.assertEqual(res["status"], "success")
        self.assertEqual(executed, ["action_1", "action_3"])

    def test_failure_recovery_branching(self):
        executed = []

        def mock_dispatcher(action, args):
            executed.append(action)
            if action == "flaky_action":
                return "Simulated failure", True
            return {"status": "recovered"}, False

        executor = DAGExecutor(tool_dispatcher=mock_dispatcher)

        steps = [
            {
                "id": "s1",
                "action": "flaky_action",
                "on_failure": {"strategy": "branch", "target_step": "recovery_step"}
            },
            {
                "id": "s2",
                "action": "never_run",
            },
            {
                "id": "recovery_step",
                "action": "do_recovery",
            }
        ]

        res = executor.run_dag(steps, stop_on_error=True)
        self.assertEqual(res["status"], "success")
        self.assertIn("flaky_action", executed)
        self.assertNotIn("never_run", executed)
        self.assertIn("do_recovery", executed)


if __name__ == "__main__":
    unittest.main()
