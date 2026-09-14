import sys
import unittest

# Allow the domain package to be imported without Docker deps.
for mod in ["temporalio", "mlflow", "fastapi", "pydantic", "sentry_sdk", "numpy", "sklearn"]:
    sys.modules.setdefault(mod, __import__("types").ModuleType(mod))
sys.path.insert(0, "packages")

from ml_platform.context_serving import routing as rt
from ml_platform.context_modelregistry import model as mr
from ml_platform.context_lifecycle import orchestrator as orch
from ml_platform import model_kinds as mk


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


class TestTrainerVocabulary(unittest.TestCase):
    """The estimator kinds, and what a training request resolves to.

    These are the rules the api's `TrainRequest` refuses a bad call with and the
    worker trains by, tested where they live — in the shared package — because
    there is only one copy of them and two services that must agree.
    """

    def test_the_three_knob_call_still_means_what_it_always_meant(self):
        """A request with no kind trains the original estimator, with its defaults.

        The console posted exactly these three numbers before a family could be
        chosen; a caller that still does must get the same training, not a 4xx and
        not a different estimator. An omitted knob is absent, so the *kind's*
        default applies — 3 and 0.08 below — rather than a value overwriting it.
        """
        kind, params, problem = mk.resolve_request(
            "", None, {"n_estimators": 150, "max_depth": None, "learning_rate": None}
        )
        self.assertIsNone(problem)
        self.assertEqual(kind, mk.DEFAULT_KIND)
        self.assertEqual(params, {"n_estimators": 150, "max_depth": 3, "learning_rate": 0.08})

    def test_an_omitted_request_trains_the_original_estimator(self):
        _, params, problem = mk.resolve_request("", None, None)
        self.assertIsNone(problem)
        self.assertEqual(params, {"n_estimators": 120, "max_depth": 3, "learning_rate": 0.08})

    def test_the_kind_and_its_parameters_are_the_same_call_as_the_flat_knobs(self):
        """The panel's shape and the old shape resolve to the identical training.

        This is what keeps them one trainer rather than two paths: `params` for the
        default kind *is* the three knobs, so the idempotency key the trainer builds
        from them is the same key either way.
        """
        flat = mk.resolve_request("", None, {"n_estimators": 150, "max_depth": 4,
                                           "learning_rate": 0.09})
        shaped = mk.resolve_request("gradient_boosting",
                                    {"n_estimators": 150, "max_depth": 4, "learning_rate": 0.09})
        self.assertEqual(flat, shaped)

    def test_an_unknown_kind_is_refused_and_both_kinds_are_named(self):
        kind, params, problem = mk.resolve_request("random_forest", {})
        self.assertIsNone(params)
        self.assertIn("random_forest", problem)
        for name in mk.kind_names():
            self.assertIn(name, problem)

    def test_an_out_of_range_parameter_is_refused_by_its_own_bound(self):
        for kind, params, expected in [
            ("logistic_regression", {"C": 0}, "0.001"),          # exclusive lower bound
            ("logistic_regression", {"max_iter": 5}, "2000"),
            ("gradient_boosting", {"n_estimators": 5000}, "1000"),
            ("gradient_boosting", {"max_depth": 0}, "10"),
        ]:
            with self.subTest(kind=kind, params=params):
                _, resolved, problem = mk.resolve_request(kind, params)
                self.assertIsNone(resolved)
                self.assertIn(expected, problem)

    def test_another_kinds_parameter_is_refused_rather_than_ignored(self):
        """A knob the chosen family does not have must not be silently dropped.

        It is the mistake a human makes most easily now that the panel offers a
        family: leave `n_estimators` filled in, switch to the linear model, press
        train. Quietly training with `C`'s default instead would be a version
        nobody asked for.
        """
        _, params, problem = mk.resolve_request("logistic_regression", {"n_estimators": 100})
        self.assertIsNone(params)
        self.assertIn("n_estimators", problem)
        self.assertIn("C", problem)  # the refusal names what the kind does take

    def test_the_catalog_the_console_is_generated_from_carries_every_spec_key(self):
        """A key added to a parameter spec must not vanish on its way to the panel.

        The panel is generated from `catalog()`, so a key that stopped being
        carried here would be a parameter the operator silently stopped seeing —
        and `exclusive_min` is precisely the kind of detail a hand-written panel
        would have dropped.
        """
        catalog = mk.catalog()
        self.assertEqual(catalog["default_kind"], mk.DEFAULT_KIND)
        self.assertEqual([k["kind"] for k in catalog["kinds"]], mk.kind_names())
        for entry in catalog["kinds"]:
            spec = mk.KINDS[entry["kind"]]["params"]
            self.assertEqual({p["name"] for p in entry["params"]}, set(spec))
            for param in entry["params"]:
                pspec = spec[param["name"]]
                # Every spec key is carried, `type` excepted (it is the Python name
                # of `json_type`, and the console speaks JSON); `name` is added, and
                # `exclusive_min` is normalised to an explicit boolean — asserted
                # below rather than allowed to go missing with no bound at all.
                self.assertEqual(set(param) - {"name"},
                                 set(pspec) - {"type"} | {"exclusive_min"})
                self.assertEqual(param["exclusive_min"], bool(pspec.get("exclusive_min", False)))
                self.assertEqual(param["default"], pspec["default"])


if __name__ == "__main__":
    unittest.main()
