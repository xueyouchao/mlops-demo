import sys
import unittest

# Allow the domain package to be imported without Docker deps.
for mod in ["temporalio", "mlflow", "fastapi", "pydantic", "sentry_sdk", "numpy", "sklearn"]:
    sys.modules.setdefault(mod, __import__("types").ModuleType(mod))
sys.path.insert(0, "packages")

from ml_platform.context_serving import routing as rt
from ml_platform.context_modelregistry import model as mr
from ml_platform.context_lifecycle import orchestrator as orch


class FakePort(orch.LifecyclePort):
    def __init__(self):
        self.wf = None

    def start_promotion(self, e):
        self.wf = "wf-" + e.version_id
        return self.wf

    def wait_for_approval(self, wid):
        return True


class TestRouting(unittest.TestCase):
    def test_canary_and_rollback(self):
        r = rt.RoutingPolicy("bc")
        r.promote_to("1")
        self.assertEqual(r.weights, {"1": 100})
        r.add_canary("2", 10)
        self.assertEqual(r.weights, {"1": 90, "2": 10})
        self.assertEqual(r.canary_versions, ["2"])
        r.rollback_to("2")
        self.assertEqual(r.weights, {"2": 100})

    def test_weights_must_sum_100(self):
        r = rt.RoutingPolicy("bc")
        with self.assertRaises(ValueError):
            r.set_weights({"1": 50, "2": 30})


class TestLifecycle(unittest.TestCase):
    def test_promote_with_approval_and_outbox(self):
        m = mr.Model("bc")
        r = rt.RoutingPolicy("bc")
        out = []
        lc = orch.ModelLifecycle(registry=m, routing=r, port=FakePort(), event_sink=out)
        lc.register_and_stage("1", "run-a", "s3://x")
        lc.request_production_promotion("1", actor="op")
        lc.confirm_approval("1", "wf-1", approved_by="op")
        self.assertEqual(m.production_version.version_id, "1")
        names = [type(e).__name__ for e in out]
        self.assertIn("PromotionApprovalRequested", names)
        self.assertIn("ModelPromotedToProduction", names)

    def test_rollback_event_names_the_displaced_version(self):
        """The audit event must name what the rollback *displaced*, not the target.

        `registry.rollback` moves the production pointer itself, so a
        `previous_version_id` read after the move returns the target version —
        every rollback then recorded "moved from v1 to v1", which is what the
        console prints verbatim. Fails on that behaviour: it asserts v2.
        """
        m = mr.Model("bc")
        r = rt.RoutingPolicy("bc")
        out = []
        lc = orch.ModelLifecycle(registry=m, routing=r, port=FakePort(), event_sink=out)
        for v in ("1", "2"):
            lc.register_and_stage(v, f"run-{v}", f"s3://{v}")
        # v1 goes live, then v2 displaces it — so v1 is the version a later
        # rollback back to v1 has to name as the one it displaced.
        lc.confirm_approval("1", "wf-1", approved_by="op")
        lc.confirm_approval("2", "wf-2", approved_by="op")

        lc.rollback("1", actor="op")

        event = out[-1]
        self.assertEqual(type(event).__name__, "ModelRolledBack")
        self.assertEqual(event.version_id, "1")
        self.assertEqual(event.previous_version_id, "2")
        self.assertEqual(m.production_version.version_id, "1")
        self.assertEqual(r.weights, {"1": 100})

    def test_rollback_to_the_version_already_serving_keeps_it_live(self):
        """Re-pinning the incumbent must not demote the version it just marked live.

        `DEMO_INCUMBENT=weakest` picks the same weak incumbent on every reset, so
        rolling back to the version already serving is the normal path now. The
        second pass used to overwrite its own assignment — mark the target
        PRODUCTION, then demote "the previous production pointer", which *was* that
        target — leaving a production pointer on a version reading STAGING, so the
        console's version table showed no production version while the router
        served one. Fails on that behaviour: it asserts the stage, not the pointer.
        """
        m = mr.Model("bc")
        r = rt.RoutingPolicy("bc")
        lc = orch.ModelLifecycle(registry=m, routing=r, port=FakePort(), event_sink=[])
        for v in ("1", "2"):
            lc.register_and_stage(v, f"run-{v}", f"s3://{v}")
        lc.confirm_approval("1", "wf-1", approved_by="op")

        lc.rollback("1", actor="op")  # back to the version already serving
        lc.rollback("1", actor="op")  # and again, as a repeated reset does

        self.assertEqual(m.production_version.version_id, "1")
        self.assertEqual(m.production_version.stage, mr.Stage.PRODUCTION)
        self.assertEqual(r.weights, {"1": 100})


if __name__ == "__main__":
    unittest.main()
