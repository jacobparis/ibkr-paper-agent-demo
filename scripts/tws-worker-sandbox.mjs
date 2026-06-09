import "dotenv/config";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { installDocker, run, uploadTextFile } from "./sandbox-helpers.mjs";

const GATEWAY_IMAGE = "ghcr.io/gnzsnz/ib-gateway:stable";

export async function buildTwsWorker(sandbox) {
  await run(sandbox, "mkdir -p /vercel/sandbox/tws-worker/workers /vercel/sandbox/state");
  await uploadTextFile(
    sandbox,
    "containers/tws-worker/Dockerfile",
    "/vercel/sandbox/tws-worker/Dockerfile",
  );
  await uploadTextFile(
    sandbox,
    "workers/tws_worker.py",
    "/vercel/sandbox/tws-worker/workers/tws_worker.py",
  );
  await run(
    sandbox,
    "cd /vercel/sandbox/tws-worker && sudo docker build --tag tws-worker .",
  );
}

export async function prepareTwsWorkerSandbox(sandbox) {
  await installDocker(sandbox);
  await buildTwsWorker(sandbox);
}

export async function resetTwsWorkerState(sandbox) {
  await run(
    sandbox,
    [
      "mkdir -p /vercel/sandbox/state",
      "rm -f /vercel/sandbox/state/audit.jsonl",
      "rm -f /vercel/sandbox/state/intent.json",
      "rm -f /vercel/sandbox/state/tws-password",
      "sudo docker rm -f ib-gateway >/dev/null 2>&1 || true",
    ].join(" && "),
  );
}

export async function startIbGateway(sandbox, {
  username = process.env.TWS_USERID,
  password = process.env.TWS_PASSWORD,
  readOnlyApi = false,
} = {}) {
  if (!username || !password) {
    throw new Error("Set TWS_USERID and TWS_PASSWORD for the IB Gateway login");
  }
  const hostPort = 4002;
  const containerPort = 4004;
  await run(sandbox, "mkdir -p /vercel/sandbox/state");
  await sandbox.fs.writeFile("/vercel/sandbox/state/tws-password", password, {
    mode: 0o600,
  });
  const hasGatewayImage = await run(
    sandbox,
    `sudo docker image inspect ${GATEWAY_IMAGE} >/dev/null 2>&1`,
  )
    .then(() => true)
    .catch(() => false);
  if (!hasGatewayImage) {
    await run(sandbox, `sudo docker pull ${GATEWAY_IMAGE}`);
  }
  await run(
    sandbox,
    [
      "sudo docker run --detach --name ib-gateway",
      "  --env TWS_USERID",
      "  --env TWS_PASSWORD_FILE=/run/secrets/tws-password",
      "  --env TRADING_MODE=paper",
      `  --env READ_ONLY_API=${readOnlyApi ? "yes" : "no"}`,
      "  --volume /vercel/sandbox/state/tws-password:/run/secrets/tws-password:ro",
      `  --publish 127.0.0.1:${hostPort}:${containerPort}`,
      `  ${GATEWAY_IMAGE}`,
    ].join(" \\\n"),
    { env: { TWS_USERID: username } },
  );
  return { hostPort };
}

export async function cleanupIbGateway(sandbox) {
  await run(
    sandbox,
    [
      "sudo docker rm -f ib-gateway >/dev/null 2>&1 || true",
      "rm -f /vercel/sandbox/state/tws-password",
    ].join(" && "),
  );
}

export async function runTwsWorker(sandbox, {
  args,
  env = {},
} = {}) {
  const envArgs = Object.entries(env)
    .map(([key, value]) => `--env ${key}=${shellQuote(value)}`)
    .join(" ");
  return run(
    sandbox,
    [
      "sudo docker run --rm --network host",
      "  --volume /vercel/sandbox/state:/state",
      `  ${envArgs}`,
      "  tws-worker",
      `  ${args.map(shellQuote).join(" ")}`,
    ].join(" \\\n"),
  );
}

export async function downloadAudit(sandbox, outputDir = "work") {
  const remote = "/vercel/sandbox/state/audit.jsonl";
  const exists = await sandbox.fs
    .stat(remote)
    .then(() => true)
    .catch(() => false);
  if (!exists) return null;
  await mkdir(outputDir, { recursive: true });
  const content = await sandbox.fs.readFile(remote, "utf8");
  const path = join(outputDir, `tws-audit-${Date.now()}.jsonl`);
  await writeFile(path, content);
  return path;
}

export async function inspectGateway(sandbox) {
  const { stdout } = await run(
    sandbox,
    "sudo docker logs --tail 120 ib-gateway 2>&1",
  );
  return stdout;
}

export async function downloadGatewayLogs(sandbox, outputDir = "work") {
  const content = await inspectGateway(sandbox);
  await mkdir(outputDir, { recursive: true });
  const path = join(outputDir, `ibgateway-${Date.now()}.log`);
  await writeFile(path, content);
  return path;
}

export function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\"'\"'")}'`;
}
