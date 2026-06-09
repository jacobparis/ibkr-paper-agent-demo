import assert from "node:assert/strict";
import test from "node:test";
import {
  authenticationPreflight,
  authenticationTimeoutError,
  AUTH_READY_ACK,
  IBKR_PORTAL_LOGIN_URL,
  requireAuthenticationReadiness,
} from "../scripts/auth-guidance";

test("authentication preflight confirms readiness", () => {
  const message = authenticationPreflight();

  assert.equal(message, "[auth] browser-auth readiness confirmed; starting IBKR paper Gateway");
});

test("authentication timeout retains the latest readiness error", () => {
  const cause = new Error("connection refused");
  const error = authenticationTimeoutError({
    cause,
  });

  assert.equal(error.cause, cause);
  assert.match(error.message, /did not become API-ready/);
  assert.match(error.message, /\[agent-action\] Ask the user to open/);
  assert.match(error.message, new RegExp(escapeRegex(IBKR_PORTAL_LOGIN_URL)));
  assert.match(error.message, /Do not paste the SMS code into agent chat or the terminal/);
  assert.match(error.message, /Most recent readiness error: connection refused/);
});

test("credentialed commands require a prominent browser-auth checkpoint", () => {
  assert.throws(
    () => requireAuthenticationReadiness(),
    (error: unknown) => {
      const message = (error as Error).message;
      assert.match(message, /USER ACTION REQUIRED: IBKR BROWSER AUTHENTICATION CHECKPOINT/);
      assert.match(message, /Reply done to the coding agent/);
      assert.match(message, new RegExp(escapeRegex(IBKR_PORTAL_LOGIN_URL)));
      assert.match(message, /Do not paste an IBKR password or SMS code/);
      assert.match(message, new RegExp(`IBKR_AUTH_READY=${AUTH_READY_ACK}`));
      return true;
    },
  );

  assert.doesNotThrow(() => requireAuthenticationReadiness({
    acknowledgement: AUTH_READY_ACK,
  }));
});

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
