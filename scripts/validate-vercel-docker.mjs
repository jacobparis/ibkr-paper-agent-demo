import { createSandbox, installDocker, run } from "./sandbox-helpers.mjs";

const sandbox = await createSandbox();
console.log(`[sandbox] created ${sandbox.name}`);

try {
  await installDocker(sandbox);
  await run(
    sandbox,
    "sudo docker run --rm hello-world >/dev/null",
  );
  console.log("[validate:docker] PASS");
} finally {
  await sandbox.stop();
  await sandbox.delete();
}
