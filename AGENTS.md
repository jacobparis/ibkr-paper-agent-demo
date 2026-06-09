# Coding Agent Runbook

Operate this repository as a paper-only demo. Keep secrets in the user's
ignored local `.env`. Never ask for an IBKR password or SMS code in chat.

## Safety

- Never choose executable prices silently.
- Reconcile before a write and run `whatif` before submission.
- Show the exact bracket and wait for explicit approval.
- Submit once. If the result is uncertain, reconcile the same intent ID before
  any retry.
- Explain that a `GTC` entry stays active at IBKR after Sandbox shutdown until
  fill or cancellation.
- Report broker acceptance separately from execution.

## Bootstrap

```bash
npm install
vercel link
vercel env pull .env.local
npm test
npm run validate:ondemand-worker
cp .env.example .env
```

Ask the user to fill `.env` locally with paper credentials, the `DU...`
account ID, and the three bracket prices. Do not ask them to paste the values.
The default `GTC` entry also requires the durable-entry acknowledgement shown
in `.env.example`. For automatic expiry, the user can set `IBKR_ENTRY_TIF=GTD`
and `IBKR_ENTRY_TTL_SECONDS`.

## Credentialed Workflow

Generate and locally validate the intent:

```bash
npm run worker:intent
```

Trigger the authentication checkpoint before creating a Sandbox:

```bash
npm run worker:remote -- reconcile
```

Relay the emitted `USER ACTION REQUIRED` block verbatim and wait for the user
to reply `done`. The user completes any SMS challenge on the IBKR website only.
Do not store `IBKR_AUTH_READY` in `.env`.

After `done`, reconcile and run broker validation:

```bash
IBKR_AUTH_READY=YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER \
  npm run worker:remote -- reconcile
IBKR_AUTH_READY=YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER \
  npm run worker:remote -- whatif work/paper-bracket-intent.json
```

Show the user: side, quantity, symbol, entry limit, take-profit limit,
stop-loss price, entry lifetime, outside-RTH setting, and the `whatif` result.
Submit only after approval of that exact bracket:

```bash
IBKR_AUTH_READY=YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER \
IBKR_ALLOW_ORDER_SUBMISSION=YES_I_UNDERSTAND_THIS_SUBMITS_A_PAPER_BRACKET_ORDER \
  npm run worker:remote -- submit work/paper-bracket-intent.json
```

Run the prefixed reconciliation command again from a fresh Gateway session and
report:

- `BROKER_ACCEPTED`: IBKR owns the order; no fill is implied.
- `FILLED`: an execution exists.
- `EXPIRED`: a GTD entry expired without a fill.
- `REJECTED`: IBKR did not accept the order.
