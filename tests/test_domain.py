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


if __name__ == "__main__":
    unittest.main()
