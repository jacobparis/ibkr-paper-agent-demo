type WorkerOutput = {
  ok: boolean;
  error?: string;
  output: Record<string, any>;
};

export function renderWorkerOutput(stdout: string): string {
  const payload = JSON.parse(stdout) as WorkerOutput;
  if (!payload.ok) throw new Error(payload.error);
  const output = payload.output;

  if (output.event === "preview") {
    return [
      "[preview] no order submitted",
      ...renderOrders(output.plan.orders, output.plan.intent),
    ].join("\n");
  }

  if (output.event === "reconcile") {
    return renderState("reconcile", output.state).join("\n");
  }

  if (output.event === "whatif") {
    const state = output.result.orderState;
    return [
      ...renderState("before", output.before),
      `[whatif] status=${state.status} warning=${state.warningText?.trim() || "none"} commission=${state.commission ?? "unknown"} ${state.commissionCurrency ?? ""}`.trim(),
      ...renderOrders(output.plan.orders, output.plan.intent),
    ].join("\n");
  }

  if (output.event === "submit") {
    return [
      ...renderState("before", output.before),
      `[submit] brokerAccepted=true duplicate=${output.result.duplicate}`,
      ...renderOrders(output.result.orders),
      ...renderState("after", output.after, { includeOrders: false }),
    ].join("\n");
  }

  return `[worker] event=${output.event}`;
}

function renderState(
  label: string,
  state: Record<string, any>,
  { includeOrders = true }: { includeOrders?: boolean } = {},
): string[] {
  const positions = state.positions ?? [];
  const openOrders = flattenOrders(state.openOrders ?? []);
  const executions = state.executions ?? [];
  return [
    `[${label}] positions=${positions.length} openOrders=${openOrders.length} executions=${executions.length}`,
    ...(includeOrders ? renderOrders(openOrders) : []),
  ];
}

function flattenOrders(orders: Record<string, any>[]): Record<string, any>[] {
  return orders.flatMap((order) => order.orders ?? [order]);
}

function renderOrders(
  orders: Record<string, any>[],
  intent: Record<string, any> = {},
): string[] {
  return orders.map((order) => {
    const symbol = order.symbol ?? intent.symbol;
    const quantity = order.quantity ?? intent.quantity;
    const price = order.type === "STP"
      ? `stop=${order.stopPrice}`
      : `limit=${order.limitPrice}`;
    const fields = [
      `[order] ${order.role} ${order.action} ${quantity} ${symbol} ${order.type}`,
      price,
      `tif=${order.tif}`,
    ];
    if (order.permId) fields.push(`permId=${order.permId}`);
    if (order.status) fields.push(`status=${order.status}`);
    if (order.whyHeld) fields.push(`held=${order.whyHeld}`);
    return fields.join(" ");
  });
}
