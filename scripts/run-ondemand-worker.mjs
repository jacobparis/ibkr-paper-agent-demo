import "dotenv/config";
import { Sandbox } from "@vercel/sandbox";
import { readFile } from "node:fs/promises";
import {
  authenticationPreflight,
  authenticationTimeoutError,
  requireAuthenticationReadiness,
} from "./auth-guidance.mjs";
import {
  cleanupIbGateway,
  downloadAudit,
  downloadGatewayLogs,
  prepareTwsWorkerSandbox,
  resetTwsWorkerState,
  runTwsWorker,
  startIbGateway,
} from "./tws-worker-sandbox.mjs";
import { renderWorkerOutput } from "./render-worker-output.mjs";

const command = process.argv[2] ?? "reconcile";
const intentFile = process.argv[3];
if (!["reconcile", "submit", "whatif"].includes(command)) {
  throw new Error("Usage: npm run worker:remote -- <reconcile|whatif|submit> [intent.json]");
}
if (command !== "reconcile" && !intentFile) {
  throw new Error(`${command} requires an intent JSON file`);
}

const timeout = Number(process.env.IBKR_SANDBOX_TIMEOUT_MS ?? 45 * 60 * 1000);
const sandboxName = process.env.IBKR_SANDBOX_NAME ?? "ibkr-paper-agent";
try {
  requireAuthenticationReadiness({
    acknowledgement: process.env.IBKR_AUTH_READY,
  });
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
console.log(authenticationPreflight());
const sandbox = await Sandbox.getOrCreate({
  name: sandboxName,
  runtime: "node24",
  persistent: true,
  timeout,
});
console.log(`[sandbox] using warm ${sandbox.name}`);

try {
  await prepareTwsWorkerSandbox(sandbox);
  await resetTwsWorkerState(sandbox);
  const readOnlyApi = command === "reconcile";
  const { hostPort } = await startIbGateway(sandbox, { readOnlyApi });
  console.log(
    `[ibgateway] started paper container${readOnlyApi ? " with read-only API" : ""}; waiting for API port ${hostPort}`,
  );

  const connectionArgs = [
    "reconcile",
    "--backend",
    "ib_async",
    "--port",
    String(hostPort),
  ];
  const ready = await runWhenGatewayReady(sandbox, connectionArgs);
  const args = [command, ...connectionArgs.slice(1)];
  if (command === "submit" || command === "whatif") {
    const payload = await readFile(intentFile, "utf8");
    await sandbox.fs.writeFile("/vercel/sandbox/state/intent.json", payload);
    args.push("--intent-file", "/state/intent.json");
  }
  const result = command === "reconcile"
    ? ready
    : await runTwsWorker(sandbox, { args, env: brokerEnv() });
  console.log(renderWorkerOutput(result.stdout));
  const audit = await downloadAudit(sandbox);
  if (audit) console.log(`[audit] wrote ${audit}`);
} catch (error) {
  const audit = await downloadAudit(sandbox).catch(() => null);
  if (audit) console.error(`[audit] wrote ${audit}`);
  const logs = await downloadGatewayLogs(sandbox).catch(() => null);
  if (logs) console.error(`[ibgateway] wrote ${logs}`);
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await cleanupIbGateway(sandbox).catch(() => null);
  await sandbox.stop();
  console.log(`[sandbox] stopped and preserved ${sandbox.name}`);
}

async function runWhenGatewayReady(sandbox, args, {
  timeoutMs = 3 * 60 * 1_000,
  retryMs = 5_000,
} = {}) {
  let lastError;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      return await runTwsWorker(sandbox, { args, env: brokerEnv() });
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, retryMs));
    }
  }
  throw authenticationTimeoutError({
    cause: lastError,
  });
}

function brokerEnv() {
  return {
    IBKR_ALLOW_ORDER_SUBMISSION: process.env.IBKR_ALLOW_ORDER_SUBMISSION ?? "",
    IBKR_ALLOW_OUTSIDE_RTH: process.env.IBKR_ALLOW_OUTSIDE_RTH ?? "",
    IBKR_ALLOW_DURABLE_ENTRY: process.env.IBKR_ALLOW_DURABLE_ENTRY ?? "",
    IBKR_MAX_ENTRY_TTL_SECONDS: process.env.IBKR_MAX_ENTRY_TTL_SECONDS ?? "604800",
    IBKR_MAX_NOTIONAL_USD: process.env.IBKR_MAX_NOTIONAL_USD ?? "5000",
  };
}
