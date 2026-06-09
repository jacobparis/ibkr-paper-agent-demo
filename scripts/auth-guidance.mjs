export const AUTH_READY_ACK = "YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER";
export const IBKR_PORTAL_LOGIN_URL = "https://ndcdyn.interactivebrokers.com/sso/Login?RL=1&locale=en_US";

export function authenticationPreflight() {
  return "[auth] browser-auth readiness confirmed; starting IBKR paper Gateway";
}

export function requireAuthenticationReadiness({
  acknowledgement,
} = {}) {
  if (acknowledgement === AUTH_READY_ACK) return;
  throw new Error(
    [
      "",
      "================================================================",
      "USER ACTION REQUIRED: IBKR BROWSER AUTHENTICATION CHECKPOINT",
      "================================================================",
      "Before the coding agent starts the IBKR paper Gateway:",
      `1. Open the official IBKR login URL in your own browser: ${IBKR_PORTAL_LOGIN_URL}`,
      "2. Be ready to sign in with the paper-trading username.",
      "3. If IBKR sends an SMS code, enter it on the IBKR website only.",
      "4. Leave the authenticated website session open.",
      "5. Reply done to the coding agent.",
      "",
      "Do not paste an IBKR password or SMS code into agent chat or the terminal.",
      "",
      "[agent-action] Stop here. Relay this checkpoint to the user and wait for done.",
      `[agent-action] After the user replies done, rerun with IBKR_AUTH_READY=${AUTH_READY_ACK}`,
      "================================================================",
    ].join("\n"),
  );
}

export function authenticationTimeoutError({
  cause,
} = {}) {
  return new Error(
    [
      "[user-action-required] IBKR paper Gateway did not become API-ready.",
      `[agent-action] Ask the user to open ${IBKR_PORTAL_LOGIN_URL}, complete any IBKR security challenge, and reply done before retrying.`,
      "Do not paste the SMS code into agent chat or the terminal.",
      cause?.message ? `Most recent readiness error: ${cause.message}` : "",
    ].filter(Boolean).join("\n"),
    { cause },
  );
}
