import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace


SPEC = importlib.util.spec_from_file_location(
    "tws_worker", Path(__file__).parents[1] / "workers" / "tws_worker.py"
)
WORKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = WORKER
SPEC.loader.exec_module(WORKER)


def intent(**overrides):
    payload = {
        "intentId": "intent-1",
        "accountId": "DU1234567",
        "mode": "paper",
        "symbol": "aapl",
        "action": "BUY",
        "quantity": 1,
        "entryLimit": "100",
        "takeProfitLimit": "110",
        "stopLossPrice": "95",
        "expiresAt": "2026-06-02T12:15:00Z",
    }
    return payload | overrides


def trade(
    order_id,
    *,
    parent_id=0,
    order_type="LMT",
    action="BUY",
    limit_price=None,
    tif=None,
    good_till_date=None,
):
    limit_price = limit_price or ("100" if not parent_id else "110")
    tif = tif or ("GTD" if not parent_id else "GTC")
    good_till_date = (
        "20260602-12:15:00" if not parent_id and good_till_date is None else good_till_date or ""
    )
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="AAPL"),
        order=SimpleNamespace(
            orderId=order_id,
            permId=order_id + 10_000,
            parentId=parent_id,
            account="DU1234567",
            action=action,
            orderType=order_type,
            totalQuantity=1,
            lmtPrice=limit_price,
            auxPrice="95" if order_type == "STP" else "0",
            tif=tif,
            goodTillDate=good_till_date,
            outsideRth=False,
            orderRef="intent-1",
        ),
        orderStatus=SimpleNamespace(status="Submitted", whyHeld=""),
        advancedError="",
        log=[],
    )


class WorkerTests(unittest.TestCase):
    now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)

    def test_accepts_bounded_paper_bracket(self):
        parsed = WORKER.validate_intent(intent(), now=self.now)
        self.assertEqual(parsed.symbol, "AAPL")
        plan = WORKER.order_plan(parsed)
        self.assertEqual([order["tif"] for order in plan["orders"]], ["GTD", "GTC", "GTC"])

    def test_refuses_non_paper_account_in_paper_mode(self):
        with self.assertRaisesRegex(ValueError, "paper account IDs must start with DU"):
            WORKER.validate_intent(intent(accountId="U1234567"), now=self.now)

    def test_refuses_entry_expiring_beyond_ttl(self):
        with self.assertRaisesRegex(ValueError, "expiresAt exceeds"):
            WORKER.validate_intent(
                intent(expiresAt="2026-06-10T12:00:01Z"), now=self.now
            )

    def test_durable_gtc_entry_requires_acknowledgement(self):
        previous = os.environ.pop("IBKR_ALLOW_DURABLE_ENTRY", None)
        try:
            with self.assertRaisesRegex(ValueError, "durable GTC paper entries require"):
                WORKER.validate_intent(intent(entryTif="GTC", expiresAt=None), now=self.now)
            os.environ["IBKR_ALLOW_DURABLE_ENTRY"] = WORKER.DURABLE_ENTRY_ACK
            parsed = WORKER.validate_intent(intent(entryTif="GTC", expiresAt=None), now=self.now)
            plan = WORKER.order_plan(parsed)
            self.assertEqual(parsed.entryTif, "GTC")
            self.assertIsNone(parsed.expiresAt)
            self.assertEqual(plan["orders"][0]["tif"], "GTC")
            self.assertEqual(plan["orders"][0]["goodTillDate"], "")
        finally:
            if previous is None:
                os.environ.pop("IBKR_ALLOW_DURABLE_ENTRY", None)
            else:
                os.environ["IBKR_ALLOW_DURABLE_ENTRY"] = previous

    def test_refuses_unprotected_price_shape(self):
        with self.assertRaisesRegex(ValueError, "BUY brackets require"):
            WORKER.validate_intent(intent(stopLossPrice="105"), now=self.now)

    def test_refuses_short_entry(self):
        with self.assertRaisesRegex(ValueError, "only BUY entries are supported"):
            WORKER.validate_intent(
                intent(action="SELL", takeProfitLimit="90", stopLossPrice="105"),
                now=self.now,
            )

    def test_refuses_fractional_quantity(self):
        with self.assertRaisesRegex(ValueError, "quantity must be a whole number"):
            WORKER.validate_intent(intent(quantity=1.5), now=self.now)

    def test_requires_supported_us_listing_exchange(self):
        WORKER.ensure_us_listing(SimpleNamespace(symbol="AAPL", primaryExchange="NASDAQ"))
        with self.assertRaisesRegex(RuntimeError, "outside the supported US listing venues"):
            WORKER.ensure_us_listing(SimpleNamespace(symbol="SHOP", primaryExchange="TSE"))

    def test_normalizes_broker_gtd_formats(self):
        self.assertEqual(
            WORKER.normalize_broker_gtd("20260602-12:15:00"),
            datetime(2026, 6, 2, 12, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(
            WORKER.normalize_broker_gtd("20260602 08:15:00 US/Eastern"),
            datetime(2026, 6, 2, 12, 15, tzinfo=timezone.utc),
        )

    def test_existing_bracket_ignores_subsecond_gtd_precision(self):
        parsed = WORKER.validate_intent(
            intent(expiresAt="2026-06-02T12:15:00.308000Z"),
            now=self.now,
        )
        orders = [
            WORKER.trade_summary(trade(1000)),
            WORKER.trade_summary(trade(1001, parent_id=1000, action="SELL")),
            WORKER.trade_summary(trade(1002, parent_id=1000, order_type="STP", action="SELL")),
        ]

        WORKER.ensure_expected_bracket(parsed, orders)

    def test_existing_gtc_bracket_matches_without_expiry(self):
        previous = os.environ.pop("IBKR_ALLOW_DURABLE_ENTRY", None)
        os.environ["IBKR_ALLOW_DURABLE_ENTRY"] = WORKER.DURABLE_ENTRY_ACK
        try:
            parsed = WORKER.validate_intent(intent(entryTif="GTC", expiresAt=None), now=self.now)
            orders = [
                WORKER.trade_summary(trade(1000, tif="GTC", good_till_date="")),
                WORKER.trade_summary(trade(1001, parent_id=1000, action="SELL")),
                WORKER.trade_summary(
                    trade(1002, parent_id=1000, order_type="STP", action="SELL")
                ),
            ]

            WORKER.ensure_expected_bracket(parsed, orders)
        finally:
            if previous is None:
                os.environ.pop("IBKR_ALLOW_DURABLE_ENTRY", None)
            else:
                os.environ["IBKR_ALLOW_DURABLE_ENTRY"] = previous

    def test_outside_rth_requires_paper_acknowledgement(self):
        previous = os.environ.pop("IBKR_ALLOW_OUTSIDE_RTH", None)
        try:
            with self.assertRaisesRegex(ValueError, "outside-RTH paper orders require"):
                WORKER.validate_intent(intent(outsideRth=True), now=self.now)
            os.environ["IBKR_ALLOW_OUTSIDE_RTH"] = WORKER.OUTSIDE_RTH_ACK
            parsed = WORKER.validate_intent(intent(outsideRth=True), now=self.now)
            self.assertTrue(parsed.outsideRth)
        finally:
            if previous is None:
                os.environ.pop("IBKR_ALLOW_OUTSIDE_RTH", None)
            else:
                os.environ["IBKR_ALLOW_OUTSIDE_RTH"] = previous

    def test_mock_broker_is_idempotent_by_intent_id(self):
        parsed = WORKER.validate_intent(intent(), now=self.now)
        with tempfile.TemporaryDirectory() as directory:
            broker = WORKER.MockBroker(f"{directory}/state.json")
            first = broker.submit_bracket(parsed)
            second = broker.submit_bracket(parsed)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

    def test_refuses_live_mode(self):
        with self.assertRaisesRegex(ValueError, "only paper mode is supported"):
            WORKER.validate_intent(
                intent(mode="live", accountId="U1234567"), now=self.now
            )

    def test_ib_async_broker_reuses_existing_complete_bracket(self):
        parsed = WORKER.validate_intent(intent(), now=self.now)
        existing = [
            trade(1000),
            trade(1001, parent_id=1000, action="SELL"),
            trade(1002, parent_id=1000, order_type="STP", action="SELL"),
        ]
        broker = WORKER.IbAsyncBroker.__new__(WORKER.IbAsyncBroker)
        broker.ib = SimpleNamespace(
            reqAllOpenOrders=lambda: existing,
            trades=lambda: existing,
        )

        result = broker.submit_bracket(parsed)

        self.assertTrue(result["duplicate"])
        self.assertEqual(len(result["orders"]), 3)

    def test_ib_async_broker_refuses_partial_existing_intent(self):
        parsed = WORKER.validate_intent(intent(), now=self.now)
        existing = [trade(1000)]
        broker = WORKER.IbAsyncBroker.__new__(WORKER.IbAsyncBroker)
        broker.ib = SimpleNamespace(
            reqAllOpenOrders=lambda: existing,
            trades=lambda: existing,
        )

        with self.assertRaisesRegex(RuntimeError, "operator review required"):
            broker.submit_bracket(parsed)

    def test_ib_async_broker_refuses_conflicting_existing_intent(self):
        parsed = WORKER.validate_intent(intent(), now=self.now)
        existing = [
            trade(1000, limit_price="99"),
            trade(1001, parent_id=1000, action="SELL"),
            trade(1002, parent_id=1000, order_type="STP", action="SELL"),
        ]
        broker = WORKER.IbAsyncBroker.__new__(WORKER.IbAsyncBroker)
        broker.ib = SimpleNamespace(
            reqAllOpenOrders=lambda: existing,
            trades=lambda: existing,
        )

        with self.assertRaisesRegex(RuntimeError, "operator review required"):
            broker.submit_bracket(parsed)

    def test_ib_async_broker_waits_through_transitional_inactive_state(self):
        trades = [
            trade(1000),
            trade(1001, parent_id=1000, action="SELL"),
            trade(1002, parent_id=1000, order_type="STP", action="SELL"),
        ]
        for existing in trades:
            existing.orderStatus.status = "Inactive"
        broker = WORKER.IbAsyncBroker.__new__(WORKER.IbAsyncBroker)

        def settle(_seconds):
            for existing in trades:
                existing.orderStatus.status = "Submitted"

        broker.ib = SimpleNamespace(sleep=settle)

        broker._wait_for_acceptance(trades, timeout=0.1)

    def test_ib_async_reconcile_includes_balances_and_order_references(self):
        existing = [trade(1000)]
        broker = WORKER.IbAsyncBroker.__new__(WORKER.IbAsyncBroker)
        broker.ib = SimpleNamespace(
            reqAllOpenOrders=lambda: existing,
            accountSummary=lambda: [
                SimpleNamespace(
                    account="DU1234567",
                    tag="BuyingPower",
                    value="5000",
                    currency="USD",
                )
            ],
            managedAccounts=lambda: ["DU1234567"],
            positions=lambda: [],
            fills=lambda: [],
        )

        state = broker.reconcile()

        self.assertEqual(state["balances"][0]["tag"], "BuyingPower")
        self.assertEqual(state["openOrders"][0]["orderRef"], "intent-1")

    def test_ib_async_whatif_returns_order_state_without_placing_order(self):
        parsed = WORKER.validate_intent(intent(), now=self.now)

        @dataclass
        class FakeOrderState:
            status: str = "PreSubmitted"
            warningText: str = ""

        broker = WORKER.IbAsyncBroker.__new__(WORKER.IbAsyncBroker)
        contract = SimpleNamespace(
            symbol="AAPL",
            exchange="SMART",
            primaryExchange="NASDAQ",
            currency="USD",
            secType="STK",
        )
        broker._qualified_stock = lambda _intent: contract
        broker.ib = SimpleNamespace(whatIfOrder=lambda _contract, _order: FakeOrderState())

        previous_ib_async = sys.modules.get("ib_async")
        fake_ib_async = ModuleType("ib_async")
        fake_ib_async.LimitOrder = lambda *args, **kwargs: SimpleNamespace(
            args=args, kwargs=kwargs
        )
        sys.modules["ib_async"] = fake_ib_async
        try:
            result = broker.what_if(parsed)
        finally:
            if previous_ib_async is None:
                sys.modules.pop("ib_async", None)
            else:
                sys.modules["ib_async"] = previous_ib_async

        self.assertEqual(result["orderState"]["status"], "PreSubmitted")
        self.assertEqual(result["contract"]["primaryExchange"], "NASDAQ")

    def test_submit_error_is_audited(self):
        class RejectingBroker:
            def reconcile(self):
                return {"backend": "test"}

            def submit_bracket(self, _intent):
                raise RuntimeError("rejected for test")

            def close(self):
                pass

        payload = intent(
            expiresAt=(WORKER.utc_now() + timedelta(minutes=15))
            .isoformat()
            .replace("+00:00", "Z")
        )
        previous_ack = os.environ.get("IBKR_ALLOW_ORDER_SUBMISSION")
        previous_make_broker = WORKER.make_broker
        os.environ["IBKR_ALLOW_ORDER_SUBMISSION"] = WORKER.PAPER_SUBMIT_ACK
        WORKER.make_broker = lambda _args: RejectingBroker()
        try:
            with tempfile.TemporaryDirectory() as directory:
                audit_file = f"{directory}/audit.jsonl"
                args = SimpleNamespace(
                    intent=payload,
                    intent_file=None,
                    audit_file=audit_file,
                    preview=False,
                )
                with self.assertRaisesRegex(RuntimeError, "rejected for test"):
                    WORKER.command_submit(args)
                event = json.loads(Path(audit_file).read_text())
                self.assertEqual(event["event"], "submit-error")
                self.assertEqual(event["after"], {"backend": "test"})
        finally:
            WORKER.make_broker = previous_make_broker
            if previous_ack is None:
                os.environ.pop("IBKR_ALLOW_ORDER_SUBMISSION", None)
            else:
                os.environ["IBKR_ALLOW_ORDER_SUBMISSION"] = previous_ack


if __name__ == "__main__":
    unittest.main()
