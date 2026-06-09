---
name: ibkr-paper-agent
description: Operate the local IBKR paper-only bracket demo safely when the user asks to check status, prepare a trade, run whatif, submit an approved bracket, or inspect the warm Sandbox workflow.
---

# IBKR Paper Agent

Use this skill when operating this repository's paper-only IBKR demo.

Read `AGENTS.md` before any credentialed command. It is the authoritative
runbook.

## Rules

- Never ask for an IBKR password or SMS code in chat.
- Never choose executable prices silently.
- Reconcile before a write.
- Run `whatif` before submission.
- Show the exact bracket and wait for explicit approval.
- Submit once. If the write result is uncertain, reconcile the same intent ID
  before retrying.
- Distinguish `BROKER_ACCEPTED` from `FILLED`.

## Workflow

1. For status, run:

   ```bash
   IBKR_AUTH_READY=YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER \
     npm run worker:remote -- reconcile
   ```

2. For a new trade, use explicit user-approved prices with:

   ```bash
   IBKR_ENTRY_LIMIT=<entry> \
   IBKR_TAKE_PROFIT_LIMIT=<take-profit> \
   IBKR_STOP_LOSS_PRICE=<stop-loss> \
   IBKR_ALLOW_DURABLE_ENTRY=YES_I_UNDERSTAND_THIS_PAPER_ENTRY_REMAINS_ACTIVE_UNTIL_FILLED_OR_CANCELLED \
     npm run worker:intent
   ```

3. Run `whatif` before asking for approval:

   ```bash
   IBKR_AUTH_READY=YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER \
   IBKR_ALLOW_DURABLE_ENTRY=YES_I_UNDERSTAND_THIS_PAPER_ENTRY_REMAINS_ACTIVE_UNTIL_FILLED_OR_CANCELLED \
     npm run worker:remote -- whatif work/paper-bracket-intent.json
   ```

4. Submit only after the user approves the exact bracket:

   ```bash
   IBKR_AUTH_READY=YES_I_AM_READY_TO_COMPLETE_IBKR_AUTH_IN_MY_BROWSER \
   IBKR_ALLOW_DURABLE_ENTRY=YES_I_UNDERSTAND_THIS_PAPER_ENTRY_REMAINS_ACTIVE_UNTIL_FILLED_OR_CANCELLED \
   IBKR_ALLOW_ORDER_SUBMISSION=YES_I_UNDERSTAND_THIS_SUBMITS_A_PAPER_BRACKET_ORDER \
     npm run worker:remote -- submit work/paper-bracket-intent.json
   ```

5. Reconcile again after submit.

The runner uses the warm named Sandbox `ibkr-paper-agent` by default. It
preserves Docker and image caches, but starts a fresh Gateway session for each
broker command and clears the prior temp password, intent, and audit files.
