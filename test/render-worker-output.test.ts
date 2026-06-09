import assert from "node:assert/strict";
import test from "node:test";
import { renderWorkerOutput } from "../scripts/render-worker-output";

test("renders reconciliation without balance noise", () => {
  const output = renderWorkerOutput(JSON.stringify({
    ok: true,
    output: {
      event: "reconcile",
      state: {
        balances: [{ tag: "BuyingPower", value: "100000" }],
        positions: [],
        executions: [],
        openOrders: [{
          role: "entry",
          action: "BUY",
          quantity: 1,
          symbol: "AAPL",
          type: "LMT",
          limitPrice: "312",
          tif: "GTC",
          permId: 123,
          status: "PreSubmitted",
        }],
      },
    },
  }));

  assert.match(output, /\[reconcile\] positions=0 openOrders=1 executions=0/);
  assert.match(output, /permId=123 status=PreSubmitted/);
  assert.doesNotMatch(output, /BuyingPower|100000/);
});

test("renders what-if status, warning, commission, and planned bracket", () => {
  const output = renderWorkerOutput(JSON.stringify({
    ok: true,
    output: {
      event: "whatif",
      before: { positions: [], openOrders: [], executions: [] },
      result: {
        orderState: {
          status: "PreSubmitted",
          warningText: "",
          commission: 1,
          commissionCurrency: "USD",
        },
      },
      plan: {
        intent: { symbol: "AAPL", quantity: 1 },
        orders: [{
          role: "entry",
          action: "BUY",
          type: "LMT",
          limitPrice: "312",
          tif: "GTC",
        }],
      },
    },
  }));

  assert.match(output, /\[whatif\] status=PreSubmitted warning=none commission=1 USD/);
  assert.match(output, /\[order\] entry BUY 1 AAPL LMT limit=312 tif=GTC/);
});
