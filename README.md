# IBKR On-Demand Paper Agent

Proof of concept for running a restricted IBKR paper-trading worker in a warm
named Vercel Sandbox. Each credentialed command starts IB Gateway, reconciles
broker state, performs one operation, exports an audit file, and stops the
Sandbox while preserving Docker and image caches. IBKR owns accepted orders
after Gateway shutdown.

## Run With A Coding Agent

Give a coding agent the repository URL and this prompt:

```text
Clone this repository locally and follow AGENTS.md. Never ask me to paste an
IBKR password or SMS code into chat. Relay any USER ACTION REQUIRED block and
wait for my reply. Show me the exact paper bracket and wait for approval before
submitting once.
```

[`AGENTS.md`](AGENTS.md) is the single operator runbook.

## Scope

| Capability | Implemented boundary |
|---|---|
| Account | Paper `DU...` account only |
| Entry | Long-only SMART-routed US-listed stock limit order, 1 to 10 shares |
| Lifetime | Durable `GTC` by default; bounded `GTD` optional |
| Protection | Required GTC take-profit and stop-loss children |
| Outside RTH | Disabled unless separately acknowledged |
| Retry | Reconcile by intent ID; never blindly retry a write |
| Validation | Broker `whatIf` before submission |

This is not production-ready. Live trading is intentionally unsupported.
Production work still needs a transactional intent store, concurrency control,
scheduled reconciliation, alerting, pinned artifacts, and an operational plan
for authentication exceptions.

## Setup

```bash
npm install
vercel link
vercel env pull .env.local
cp .env.example .env
npm test
```

Fill `.env` locally. Do not paste credentials into chat.
The personal-use runner reuses the named warm Sandbox `ibkr-paper-agent` by
default. Set `IBKR_SANDBOX_NAME` locally to use another name.

## Maintainer Checks

```bash
npm test
npm run validate:docker
npm run validate:ibgateway-image
npm run validate:ondemand-worker
```

The design rationale and validation evidence are in
[`outputs/ibkr-sandbox-research.md`](outputs/ibkr-sandbox-research.md).

## Skill

The reusable Codex skill is in
[`skills/ibkr-paper-agent`](skills/ibkr-paper-agent/).
