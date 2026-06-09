#!/usr/bin/env python3
"""Bounded on-demand IB Gateway worker for broker-native bracket orders."""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PAPER_SUBMIT_ACK = "YES_I_UNDERSTAND_THIS_SUBMITS_A_PAPER_BRACKET_ORDER"
OUTSIDE_RTH_ACK = "YES_I_UNDERSTAND_THIS_PAPER_ORDER_CAN_EXECUTE_OUTSIDE_REGULAR_HOURS"
DURABLE_ENTRY_ACK = "YES_I_UNDERSTAND_THIS_PAPER_ENTRY_REMAINS_ACTIVE_UNTIL_FILLED_OR_CANCELLED"
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")
INTENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
US_PRIMARY_EXCHANGES = {"AMEX", "ARCA", "NASDAQ", "NYSE"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("expiresAt must include a timezone")
    return parsed.astimezone(timezone.utc)


def money(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"{name} must be a decimal number") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def shares(value: Any) -> int:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError("quantity must be a whole number") from error
    if parsed != parsed.to_integral_value():
        raise ValueError("quantity must be a whole number")
    return int(parsed)


@dataclass(frozen=True)
class BracketIntent:
    intentId: str
    accountId: str
    mode: str
    symbol: str
    action: str
    quantity: int
    entryLimit: str
    takeProfitLimit: str
    stopLossPrice: str
    entryTif: str
    expiresAt: str | None = None
    exchange: str = "SMART"
    currency: str = "USD"
    securityType: str = "STK"
    outsideRth: bool = False


def validate_intent(payload: dict[str, Any], *, now: datetime | None = None) -> BracketIntent:
    now = now or utc_now()
    mode = str(payload.get("mode", "paper")).lower()
    account_id = str(payload.get("accountId", ""))
    symbol = str(payload.get("symbol", "")).strip().upper()
    action = str(payload.get("action", "")).strip().upper()
    intent_id = str(payload.get("intentId", "")).strip()
    quantity = shares(payload.get("quantity", 0))
    entry = money(payload.get("entryLimit"), "entryLimit")
    take_profit = money(payload.get("takeProfitLimit"), "takeProfitLimit")
    stop_loss = money(payload.get("stopLossPrice"), "stopLossPrice")
    expires_at_value = payload.get("expiresAt")
    entry_tif = str(payload.get("entryTif", "GTD" if expires_at_value else "GTC")).strip().upper()
    expires_at = parse_utc(str(expires_at_value)) if entry_tif == "GTD" else None
    outside_rth = payload.get("outsideRth", False)
    max_ttl = int(os.getenv("IBKR_MAX_ENTRY_TTL_SECONDS", "604800"))
    max_notional = money(os.getenv("IBKR_MAX_NOTIONAL_USD", "5000"), "IBKR_MAX_NOTIONAL_USD")

    if mode != "paper":
        raise ValueError("only paper mode is supported")
    if not account_id:
        raise ValueError("accountId is required")
    if not account_id.startswith("DU"):
        raise ValueError("paper account IDs must start with DU")
    if not INTENT_ID_PATTERN.fullmatch(intent_id):
        raise ValueError("intentId must contain only letters, numbers, dot, underscore, colon, or hyphen")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("symbol must be a simple stock ticker")
    if action != "BUY":
        raise ValueError("only BUY entries are supported; bracket children close the long position")
    if quantity < 1 or quantity > 10:
        raise ValueError("quantity must be between 1 and 10 shares")
    if quantity * entry > max_notional:
        raise ValueError("entry notional exceeds IBKR_MAX_NOTIONAL_USD")
    if payload.get("exchange", "SMART") != "SMART":
        raise ValueError("only SMART routing is supported")
    if payload.get("currency", "USD") != "USD":
        raise ValueError("only USD stocks are supported")
    if payload.get("securityType", "STK") != "STK":
        raise ValueError("only STK contracts are supported")
    if not isinstance(outside_rth, bool):
        raise ValueError("outsideRth must be a boolean")
    if entry_tif not in {"GTC", "GTD"}:
        raise ValueError("entryTif must be GTC or GTD")
    if entry_tif == "GTC":
        if expires_at_value:
            raise ValueError("expiresAt is supported only for GTD entries")
        if os.getenv("IBKR_ALLOW_DURABLE_ENTRY") != DURABLE_ENTRY_ACK:
            raise ValueError("durable GTC paper entries require the explicit acknowledgement")
    if outside_rth:
        if os.getenv("IBKR_ALLOW_OUTSIDE_RTH") != OUTSIDE_RTH_ACK:
            raise ValueError("outside-RTH paper orders require the explicit acknowledgement")
    if entry_tif == "GTD":
        if expires_at <= now + timedelta(seconds=30):
            raise ValueError("expiresAt must be more than 30 seconds in the future")
        if expires_at > now + timedelta(seconds=max_ttl):
            raise ValueError("expiresAt exceeds IBKR_MAX_ENTRY_TTL_SECONDS")
    if not take_profit > entry > stop_loss:
        raise ValueError("BUY brackets require takeProfitLimit > entryLimit > stopLossPrice")

    return BracketIntent(
        intentId=intent_id,
        accountId=account_id,
        mode=mode,
        symbol=symbol,
        action=action,
        quantity=quantity,
        entryLimit=str(entry),
        takeProfitLimit=str(take_profit),
        stopLossPrice=str(stop_loss),
        entryTif=entry_tif,
        expiresAt=expires_at.isoformat().replace("+00:00", "Z") if expires_at else None,
        outsideRth=outside_rth,
    )


def order_plan(intent: BracketIntent) -> dict[str, Any]:
    exit_action = "SELL" if intent.action == "BUY" else "BUY"
    return {
        "intent": asdict(intent),
        "orders": [
            {
                "role": "entry",
                "action": intent.action,
                "type": "LMT",
                "limitPrice": intent.entryLimit,
                "tif": intent.entryTif,
                "goodTillDate": intent.expiresAt or "",
                "transmit": False,
                "outsideRth": intent.outsideRth,
            },
            {
                "role": "take-profit",
                "action": exit_action,
                "type": "LMT",
                "limitPrice": intent.takeProfitLimit,
                "tif": "GTC",
                "parent": "entry",
                "transmit": False,
                "outsideRth": intent.outsideRth,
            },
            {
                "role": "stop-loss",
                "action": exit_action,
                "type": "STP",
                "stopPrice": intent.stopLossPrice,
                "tif": "GTC",
                "parent": "entry",
                "transmit": True,
                "outsideRth": intent.outsideRth,
            },
        ],
    }


class MockBroker:
    def __init__(self, state_file: str):
        self.path = Path(state_file)
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "accounts": ["DU1234567"],
                "positions": [],
                "openOrders": [],
                "executions": [],
                "nextOrderId": 1000,
            }
        return json.loads(self.path.read_text())

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2) + "\n")

    def reconcile(self) -> dict[str, Any]:
        return copy.deepcopy(self.state) | {"backend": "mock"}

    def submit_bracket(self, intent: BracketIntent) -> dict[str, Any]:
        existing = next(
            (order for order in self.state["openOrders"] if order["intentId"] == intent.intentId),
            None,
        )
        if existing:
            return {"backend": "mock", "duplicate": True, "orders": existing["orders"]}
        plan = order_plan(intent)
        next_id = self.state["nextOrderId"]
        for index, order in enumerate(plan["orders"]):
            order["orderId"] = next_id + index
            if index:
                order["parentId"] = next_id
        self.state["nextOrderId"] += len(plan["orders"])
        self.state["openOrders"].append(
            {"intentId": intent.intentId, "accountId": intent.accountId, "orders": plan["orders"]}
        )
        self._save()
        return {"backend": "mock", "duplicate": False, "orders": plan["orders"]}

    def close(self) -> None:
        pass


class IbAsyncBroker:
    def __init__(self, host: str, port: int, client_id: int):
        try:
            from ib_async import IB
        except ImportError as error:
            raise RuntimeError("Install ib_async==2.1.0 for the real IB Gateway backend") from error
        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id, timeout=20)

    def reconcile(self) -> dict[str, Any]:
        open_trades = self.ib.reqAllOpenOrders()
        balances = [
            {
                "account": item.account,
                "tag": item.tag,
                "value": item.value,
                "currency": item.currency,
            }
            for item in self.ib.accountSummary()
        ]
        accounts = self.ib.managedAccounts()
        positions = [
            {
                "account": item.account,
                "symbol": item.contract.symbol,
                "securityType": item.contract.secType,
                "currency": item.contract.currency,
                "position": float(item.position),
                "averageCost": item.avgCost,
            }
            for item in self.ib.positions()
        ]
        open_orders = [trade_summary(trade) for trade in open_trades]
        executions = [
            {
                "executionId": fill.execution.execId,
                "orderId": fill.execution.orderId,
                "orderRef": fill.execution.orderRef,
                "account": fill.execution.acctNumber,
                "symbol": fill.contract.symbol,
                "side": fill.execution.side,
                "shares": float(fill.execution.shares),
                "price": fill.execution.price,
            }
            for fill in self.ib.fills()
        ]
        return {
            "backend": "ib_async",
            "accounts": accounts,
            "balances": balances,
            "positions": positions,
            "openOrders": open_orders,
            "executions": executions,
        }

    def submit_bracket(self, intent: BracketIntent) -> dict[str, Any]:
        duplicate = self._existing_bracket(intent)
        if duplicate:
            return {"backend": "ib_async", "duplicate": True, "orders": duplicate}

        from ib_async import LimitOrder, Stock, StopOrder

        contract = self._qualified_stock(intent)
        parent_id = self.ib.client.getReqId()
        exit_action = "SELL" if intent.action == "BUY" else "BUY"
        good_till_date = broker_good_till_date(intent)
        parent = LimitOrder(
            intent.action,
            intent.quantity,
            float(intent.entryLimit),
            orderId=parent_id,
            account=intent.accountId,
            tif=intent.entryTif,
            goodTillDate=good_till_date,
            orderRef=intent.intentId,
            transmit=False,
            outsideRth=intent.outsideRth,
        )
        take_profit = LimitOrder(
            exit_action,
            intent.quantity,
            float(intent.takeProfitLimit),
            orderId=self.ib.client.getReqId(),
            account=intent.accountId,
            tif="GTC",
            parentId=parent_id,
            orderRef=intent.intentId,
            transmit=False,
            outsideRth=intent.outsideRth,
        )
        stop_loss = StopOrder(
            exit_action,
            intent.quantity,
            float(intent.stopLossPrice),
            orderId=self.ib.client.getReqId(),
            account=intent.accountId,
            tif="GTC",
            parentId=parent_id,
            orderRef=intent.intentId,
            transmit=True,
            outsideRth=intent.outsideRth,
        )
        trades = [
            self.ib.placeOrder(contract, parent),
            self.ib.placeOrder(contract, take_profit),
            self.ib.placeOrder(contract, stop_loss),
        ]
        self._wait_for_acceptance(trades)
        return {
            "backend": "ib_async",
            "duplicate": False,
            "orders": [
                trade_summary(trade, role)
                for role, trade in zip(("entry", "take-profit", "stop-loss"), trades)
            ],
        }

    def what_if(self, intent: BracketIntent) -> dict[str, Any]:
        from ib_async import LimitOrder

        contract = self._qualified_stock(intent)
        order = LimitOrder(
            intent.action,
            intent.quantity,
            float(intent.entryLimit),
            account=intent.accountId,
            tif=intent.entryTif,
            goodTillDate=broker_good_till_date(intent),
            orderRef=intent.intentId,
            outsideRth=intent.outsideRth,
        )
        return {
            "backend": "ib_async",
            "contract": {
                "symbol": contract.symbol,
                "exchange": contract.exchange,
                "primaryExchange": contract.primaryExchange,
                "currency": contract.currency,
                "securityType": contract.secType,
            },
            "orderState": serializable(self.ib.whatIfOrder(contract, order)),
        }

    def _qualified_stock(self, intent: BracketIntent) -> Any:
        from ib_async import Stock

        if intent.accountId not in self.ib.managedAccounts():
            raise RuntimeError(f"account {intent.accountId} is not managed by this Gateway session")
        contract = self.ib.qualifyContracts(Stock(intent.symbol, "SMART", "USD"))[0]
        ensure_us_listing(contract)
        return contract

    def _existing_bracket(self, intent: BracketIntent) -> list[dict[str, Any]] | None:
        self.ib.reqAllOpenOrders()
        trades = [
            trade for trade in self.ib.trades() if trade.order.orderRef == intent.intentId
        ]
        if not trades:
            return None
        orders = [trade_summary(trade) for trade in trades]
        ensure_expected_bracket(intent, orders)
        return orders

    def _wait_for_acceptance(self, trades: list[Any], timeout: float = 10) -> None:
        end = time.monotonic() + timeout
        while True:
            statuses = [trade.orderStatus.status for trade in trades]
            errors = [trade.advancedError for trade in trades if trade.advancedError]
            if errors:
                raise RuntimeError(f"IBKR rejected bracket: {'; '.join(errors)}")
            if any(status in {"ApiCancelled", "Cancelled"} for status in statuses):
                raise RuntimeError(f"IBKR did not accept bracket: statuses={statuses}")
            if all(
                trade.order.permId > 0
                and trade.orderStatus.status in {"PreSubmitted", "Submitted", "Filled"}
                for trade in trades
            ):
                return
            if time.monotonic() >= end:
                diagnostics = [trade_diagnostic(trade) for trade in trades]
                raise RuntimeError(
                    f"timed out waiting for IBKR acceptance: {json.dumps(diagnostics, default=str)}"
                )
            self.ib.sleep(0.25)

    def close(self) -> None:
        self.ib.disconnect()


def trade_summary(trade: Any, role: str | None = None) -> dict[str, Any]:
    order = trade.order
    if role is None:
        role = "entry" if not order.parentId else "stop-loss" if order.orderType == "STP" else "take-profit"
    return {
        "role": role,
        "orderId": order.orderId,
        "permId": order.permId,
        "parentId": order.parentId,
        "account": order.account,
        "symbol": trade.contract.symbol,
        "action": order.action,
        "type": order.orderType,
        "quantity": float(order.totalQuantity),
        "limitPrice": str(order.lmtPrice),
        "stopPrice": str(order.auxPrice),
        "tif": order.tif,
        "goodTillDate": order.goodTillDate,
        "outsideRth": order.outsideRth,
        "orderRef": order.orderRef,
        "status": trade.orderStatus.status,
        "whyHeld": trade.orderStatus.whyHeld,
    }


def trade_diagnostic(trade: Any) -> dict[str, Any]:
    return trade_summary(trade) | {
        "advancedError": trade.advancedError,
        "log": [
            {
                "time": entry.time.isoformat(),
                "status": entry.status,
                "message": entry.message,
                "errorCode": entry.errorCode,
            }
            for entry in trade.log
        ],
    }


def ensure_us_listing(contract: Any) -> None:
    if contract.primaryExchange not in US_PRIMARY_EXCHANGES:
        allowed = ", ".join(sorted(US_PRIMARY_EXCHANGES))
        raise RuntimeError(
            f"{contract.symbol} primary exchange {contract.primaryExchange!r} is outside the supported US listing venues: {allowed}"
        )


def ensure_expected_bracket(intent: BracketIntent, orders: list[dict[str, Any]]) -> None:
    roles = {order["role"]: order for order in orders}
    if len(orders) != 3 or set(roles) != {"entry", "take-profit", "stop-loss"}:
        raise RuntimeError(
            f"existing intent {intent.intentId} does not have one complete bracket; operator review required"
        )
    entry = roles["entry"]
    take_profit = roles["take-profit"]
    stop_loss = roles["stop-loss"]
    children = [take_profit, stop_loss]
    exit_action = "SELL" if intent.action == "BUY" else "BUY"
    if (
        any(order["account"] != intent.accountId for order in orders)
        or any(order["symbol"] != intent.symbol for order in orders)
        or entry["action"] != intent.action
        or any(order["action"] != exit_action for order in children)
        or any(order["quantity"] != intent.quantity for order in orders)
        or any(order["parentId"] != entry["orderId"] for order in children)
        or entry["type"] != "LMT"
        or entry["tif"] != intent.entryTif
        or not entry_expiry_matches(intent, entry["goodTillDate"])
        or not same_decimal(entry["limitPrice"], intent.entryLimit)
        or take_profit["type"] != "LMT"
        or take_profit["tif"] != "GTC"
        or not same_decimal(take_profit["limitPrice"], intent.takeProfitLimit)
        or stop_loss["type"] != "STP"
        or stop_loss["tif"] != "GTC"
        or not same_decimal(stop_loss["stopPrice"], intent.stopLossPrice)
        or entry["outsideRth"] != intent.outsideRth
        or take_profit["outsideRth"] != intent.outsideRth
    ):
        raise RuntimeError(
            f"existing intent {intent.intentId} does not match the requested bracket; operator review required"
        )


def same_decimal(actual: Any, expected: Any) -> bool:
    try:
        return Decimal(str(actual)) == Decimal(str(expected))
    except Exception:
        return False


def broker_good_till_date(intent: BracketIntent) -> str:
    if intent.entryTif == "GTC":
        return ""
    return parse_utc(intent.expiresAt or "").strftime("%Y%m%d-%H:%M:%S")


def entry_expiry_matches(intent: BracketIntent, value: str) -> bool:
    if intent.entryTif == "GTC":
        return not value
    return normalize_broker_gtd(value) == parse_utc(intent.expiresAt or "").replace(microsecond=0)


def normalize_broker_gtd(value: str) -> datetime:
    for format, zone in (
        ("%Y%m%d-%H:%M:%S", timezone.utc),
        ("%Y%m%d %H:%M:%S US/Eastern", ZoneInfo("America/New_York")),
    ):
        try:
            return datetime.strptime(value, format).replace(tzinfo=zone).astimezone(timezone.utc)
        except ValueError:
            continue
    raise RuntimeError(f"unrecognized IBKR goodTillDate format: {value!r}")


def serializable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return serializable(dataclasses.asdict(value))
    if hasattr(value, "_asdict"):
        return serializable(value._asdict())
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def audit(path: str, event: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as output:
        output.write(json.dumps(event, separators=(",", ":")) + "\n")


def make_broker(args: argparse.Namespace):
    if args.backend == "mock":
        return MockBroker(args.state_file)
    return IbAsyncBroker(args.host, args.port, args.client_id)


def require_submit_ack() -> None:
    if os.getenv("IBKR_ALLOW_ORDER_SUBMISSION") != PAPER_SUBMIT_ACK:
        raise ValueError(f"paper submission requires IBKR_ALLOW_ORDER_SUBMISSION={PAPER_SUBMIT_ACK}")


def load_intent(args: argparse.Namespace) -> BracketIntent:
    if getattr(args, "intent", None):
        return validate_intent(args.intent)
    if args.intent_file:
        return validate_intent(json.loads(Path(args.intent_file).read_text()))
    raise ValueError("provide --intent-file")


def command_reconcile(args: argparse.Namespace) -> dict[str, Any]:
    broker = make_broker(args)
    try:
        state = broker.reconcile()
        event = {"at": utc_now().isoformat(), "event": "reconcile", "state": state}
        audit(args.audit_file, event)
        return event
    finally:
        broker.close()


def command_submit(args: argparse.Namespace) -> dict[str, Any]:
    intent = load_intent(args)
    plan = order_plan(intent)
    if args.preview:
        return {"at": utc_now().isoformat(), "event": "preview", "plan": plan}
    require_submit_ack()
    broker = make_broker(args)
    try:
        before = broker.reconcile()
        try:
            result = broker.submit_bracket(intent)
            after = broker.reconcile()
            event = {
                "at": utc_now().isoformat(),
                "event": "submit",
                "plan": plan,
                "before": before,
                "result": result,
                "after": after,
            }
            audit(args.audit_file, event)
            return event
        except Exception as error:
            event = {
                "at": utc_now().isoformat(),
                "event": "submit-error",
                "plan": plan,
                "before": before,
                "error": str(error),
            }
            try:
                event["after"] = broker.reconcile()
            except Exception as reconcile_error:
                event["reconcileError"] = str(reconcile_error)
            audit(args.audit_file, event)
            raise
    finally:
        broker.close()


def command_whatif(args: argparse.Namespace) -> dict[str, Any]:
    intent = load_intent(args)
    broker = make_broker(args)
    try:
        before = broker.reconcile()
        try:
            result = broker.what_if(intent)
            event = {
                "at": utc_now().isoformat(),
                "event": "whatif",
                "plan": order_plan(intent),
                "before": before,
                "result": result,
            }
            audit(args.audit_file, event)
            return event
        except Exception as error:
            event = {
                "at": utc_now().isoformat(),
                "event": "whatif-error",
                "plan": order_plan(intent),
                "before": before,
                "error": str(error),
            }
            audit(args.audit_file, event)
            raise
    finally:
        broker.close()


def command_demo(args: argparse.Namespace) -> dict[str, Any]:
    expires_at = (utc_now() + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    args.intent = {
        "intentId": "mock-demo-aapl-1",
        "accountId": "DU1234567",
        "mode": "paper",
        "symbol": "AAPL",
        "action": "BUY",
        "quantity": 1,
        "entryLimit": "100",
        "takeProfitLimit": "110",
        "stopLossPrice": "95",
        "expiresAt": expires_at,
    }
    os.environ["IBKR_ALLOW_ORDER_SUBMISSION"] = PAPER_SUBMIT_ACK
    return command_submit(args)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("command", choices=("reconcile", "submit", "whatif", "demo"))
    result.add_argument("--backend", choices=("mock", "ib_async"), default="mock")
    result.add_argument("--host", default=os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1"))
    result.add_argument("--port", type=int, default=int(os.getenv("IBKR_GATEWAY_PORT", "4002")))
    result.add_argument("--client-id", type=int, default=int(os.getenv("IBKR_CLIENT_ID", "71")))
    result.add_argument("--state-file", default=os.getenv("IBKR_MOCK_STATE_FILE", "/state/mock-broker.json"))
    result.add_argument("--audit-file", default=os.getenv("IBKR_AUDIT_FILE", "/state/audit.jsonl"))
    result.add_argument("--intent-file")
    result.add_argument("--preview", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        output = {
            "ok": True,
            "worker": "tws-ondemand-worker",
            "output": {
                "reconcile": command_reconcile,
                "submit": command_submit,
                "whatif": command_whatif,
                "demo": command_demo,
            }[args.command](args),
        }
        print(json.dumps(output, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
