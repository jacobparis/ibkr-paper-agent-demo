import "dotenv/config";
import { execFile } from "node:child_process";
import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { renderWorkerOutput } from "./render-worker-output.mjs";

const workerPath = fileURLToPath(new URL("../workers/tws_worker.py", import.meta.url));
await main().catch((error) => {
  console.error(`[intent] ${errorMessage(error)}`);
  process.exitCode = 1;
});

async function main() {
  const entryTif = (process.env.IBKR_ENTRY_TIF ?? "GTC").toUpperCase();
  if (!["GTC", "GTD"].includes(entryTif)) {
    throw new Error("IBKR_ENTRY_TIF must be GTC or GTD");
  }
  const ttlSeconds = Number(process.env.IBKR_ENTRY_TTL_SECONDS ?? 15 * 60);
  const symbol = process.env.IBKR_SYMBOL ?? "AAPL";
  const intent = {
    intentId: `paper-${symbol.toLowerCase()}-${Date.now()}`,
    accountId: required("IBKR_ACCOUNT_ID"),
    mode: "paper",
    symbol,
    action: "BUY",
    quantity: Number(process.env.IBKR_QUANTITY ?? "1"),
    entryLimit: required("IBKR_ENTRY_LIMIT"),
    takeProfitLimit: required("IBKR_TAKE_PROFIT_LIMIT"),
    stopLossPrice: required("IBKR_STOP_LOSS_PRICE"),
    entryTif,
    ...(entryTif === "GTD"
      ? { expiresAt: new Date(Date.now() + ttlSeconds * 1000).toISOString() }
      : {}),
    outsideRth: process.env.IBKR_OUTSIDE_RTH === "true",
  };

  const intentPath = "work/paper-bracket-intent.json";
  const temporaryPath = `${intentPath}.tmp`;
  await mkdir("work", { recursive: true });
  await writeFile(temporaryPath, `${JSON.stringify(intent, null, 2)}\n`);
  let stdout;
  try {
    ({ stdout } = await promisify(execFile)(
      "python3",
      [workerPath, "submit", "--intent-file", temporaryPath, "--preview"],
      { env: process.env },
    ));
  } catch (error) {
    await rm(temporaryPath, { force: true });
    throw error;
  }
  await rename(temporaryPath, intentPath);
  console.log(`[intent] wrote ${intentPath}`);
  console.log(renderWorkerOutput(stdout));
}

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function errorMessage(error) {
  try {
    return JSON.parse(error.stderr).error;
  } catch {
    return error.message;
  }
}
