import { setTimeout as sleep } from "node:timers/promises";
import { createSandbox, installDocker, run } from "./sandbox-helpers.mjs";
import { startIbGateway } from "./tws-worker-sandbox.mjs";

const sandbox = await createSandbox();
console.log(`[sandbox] created ${sandbox.name}`);

try {
  await installDocker(sandbox);
  await startIbGateway(sandbox, {
    username: "invalid-paper-demo",
    password: "invalid-paper-demo",
  });
  await sleep(15_000);

  const { stdout: state } = await run(
    sandbox,
    "sudo docker inspect --format '{{.State.Status}}' ib-gateway",
  );
  const { stdout: processes } = await run(
    sandbox,
    "sudo docker exec ib-gateway sh -lc 'ps -ef | sed -n \"1,40p\"'",
  );
  if (state.trim() !== "running") {
    throw new Error(`IB Gateway container state is ${state.trim()}`);
  }
  if (!processes.includes("IBC") && !processes.includes("ibgateway")) {
    throw new Error("IB Gateway or IBC process was not found");
  }
  console.log("[ibgateway] container running with Gateway or IBC process");
  console.log("[validate:ibgateway-image] PASS");
} finally {
  await sandbox.stop();
  await sandbox.delete();
}
