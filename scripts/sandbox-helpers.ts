import "dotenv/config";
import { readFile } from "node:fs/promises";
import { Sandbox } from "@vercel/sandbox";

export async function createSandbox(options: Record<string, unknown> = {}) {
  return Sandbox.create({
    runtime: "node24",
    timeout: 10 * 60 * 1000,
    persistent: false,
    ...options,
  });
}

export async function run(
  sandbox: Sandbox,
  command: string,
  options: Record<string, unknown> = {},
): Promise<{ stdout: string; stderr: string }> {
  const result = await sandbox.runCommand({
    cmd: "sh",
    args: ["-lc", command],
    ...options,
  });
  const stdout = await result.stdout();
  const stderr = await result.stderr();

  if (result.exitCode !== 0) {
    throw new Error(
      `Command failed (${result.exitCode}): ${command}\n${stdout}\n${stderr}`,
    );
  }
  return { stdout, stderr };
}

export async function runArgs(
  sandbox: Sandbox,
  command: string,
  args: string[],
  options: Record<string, unknown> = {},
): Promise<{ stdout: string; stderr: string }> {
  const result = await sandbox.runCommand({
    cmd: command,
    args,
    ...options,
  });
  const stdout = await result.stdout();
  const stderr = await result.stderr();

  if (result.exitCode !== 0) {
    throw new Error(
      `Command failed (${result.exitCode}): ${command} ${args.join(" ")}\n${stdout}\n${stderr}`,
    );
  }
  return { stdout, stderr };
}

export async function installDocker(sandbox: Sandbox): Promise<void> {
  const hasDocker = await run(sandbox, "command -v docker >/dev/null 2>&1")
    .then(() => true)
    .catch(() => false);
  if (!hasDocker) {
    await run(sandbox, "dnf install -y docker", { sudo: true });
  }
  const dockerReady = await run(sandbox, "sudo docker info >/dev/null 2>&1")
    .then(() => true)
    .catch(() => false);
  if (!dockerReady) {
    await sandbox.runCommand({
      cmd: "dockerd",
      sudo: true,
      detached: true,
    });
  }
  await run(
    sandbox,
    "until sudo docker info >/dev/null 2>&1; do sleep 1; done",
  );
}

export async function uploadTextFile(
  sandbox: Sandbox,
  localPath: string,
  remotePath: string,
): Promise<void> {
  const content = await readFile(localPath);
  await sandbox.writeFiles([{ path: remotePath, content }]);
}
