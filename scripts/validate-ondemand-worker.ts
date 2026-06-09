import { createSandbox } from "./sandbox-helpers";
import {
  prepareTwsWorkerSandbox,
  runTwsWorker,
} from "./tws-worker-sandbox";

const sandbox = await createSandbox({ timeout: 10 * 60 * 1000 });
console.log(`[sandbox] created ${sandbox.name}`);

try {
  await prepareTwsWorkerSandbox(sandbox);
  const { stdout: first } = await runTwsWorker(sandbox, {
    args: [
      "demo",
      "--backend",
      "mock",
      "--state-file",
      "/state/mock-broker.json",
      "--audit-file",
      "/state/audit.jsonl",
    ],
  });
  const { stdout: reconcile } = await runTwsWorker(sandbox, {
    args: [
      "reconcile",
      "--backend",
      "mock",
      "--state-file",
      "/state/mock-broker.json",
      "--audit-file",
      "/state/audit.jsonl",
    ],
  });
  const { stdout: second } = await runTwsWorker(sandbox, {
    args: [
      "demo",
      "--backend",
      "mock",
      "--state-file",
      "/state/mock-broker.json",
      "--audit-file",
      "/state/audit.jsonl",
    ],
  });

  const firstPayload = JSON.parse(first);
  const reconcilePayload = JSON.parse(reconcile);
  const secondPayload = JSON.parse(second);
  if (!firstPayload.ok || firstPayload.output.result.duplicate) {
    throw new Error("First mock submission was not accepted as a new intent");
  }
  if (reconcilePayload.output.state.openOrders.length !== 1) {
    throw new Error("Reconciliation did not recover the broker-owned bracket");
  }
  if (!secondPayload.output.result.duplicate) {
    throw new Error("Duplicate intent was not handled idempotently");
  }

  console.log("[worker] first broker-native bracket accepted");
  console.log("[worker] fresh process reconciled one open bracket");
  console.log("[worker] duplicate intent returned the existing bracket");
  console.log("[validate:ondemand-worker] PASS");
} finally {
  await sandbox.stop();
  await sandbox.delete();
}
