# IBKR On-Demand Worker: Decision Record

Updated: 2026-06-04

## Decision

Use Vercel Sandbox as a warm command runner, not as the owner of an order
lifecycle:

```text
resume named Sandbox -> start IB Gateway -> reconcile -> validate or submit one
broker-native bracket -> export audit -> stop Sandbox
```

IBKR owns a transmitted bracket after acceptance. A continuously running
Gateway is unnecessary when the strategy fits broker-native orders. For this
personal-use demo, the named Sandbox preserves Docker and image caches between
sessions.

The implemented path uses the third-party
[`gnzsnz/ib-gateway`](https://github.com/gnzsnz/ib-gateway-docker) container
and [`ib_async`](https://github.com/ib-api-reloaded/ib_async). Neither is an
IBKR-supported deployment package.

## Implemented Boundary

| Concern | Current behavior |
|---|---|
| Mode | Paper only; account ID must start with `DU` |
| Contract | SMART-routed USD stock listed on NASDAQ, NYSE, AMEX, or ARCA |
| Entry | BUY limit, 1 to 10 whole shares, configurable notional cap |
| Lifetime | Acknowledged durable `GTC`, or bounded `GTD` |
| Protection | Required GTC take-profit and stop-loss children |
| Outside RTH | Off unless separately acknowledged |
| Validation | Non-transmitting broker `whatIf` supported |
| Retry | Intent ID stored as `orderRef`; conflicting or partial matches fail |
| Audit | JSONL exported after credentialed runs |

IBKR documents bracket transmission as a parent and two opposite-side
children, with only the final child transmitting the linked group:
[Bracket Orders](https://interactivebrokers.github.io/tws-api/bracket_order.html).

## Why Reconcile Every Time

Orders can fill, reject, expire, or be changed while no Sandbox exists. Before
any write, the worker retrieves positions, current open orders, and current-day
executions, then checks the requested intent ID.

IBKR documents current open-order retrieval with `reqAllOpenOrders()`:
[TWS API reference](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-ref/).
Execution retrieval from IB Gateway is limited to the current trading day:
[TWS API documentation](https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc/).

Broker reconciliation is not a durable intent store. Production still needs
transactional submission serialization, historical audit storage, scheduled
reconciliation, and alerting.

## Authentication Constraint

The account owner may need to complete an IBKR website login and SMS challenge.
The runner therefore stops before Sandbox creation until the coding agent
relays its browser-auth checkpoint and the user confirms completion. Passwords
and SMS codes stay out of chat and the terminal.

The rejected Client Portal Gateway prototype was removed. IBKR documents that
individual-account Client Portal Gateway authentication and API calls must
occur on the same machine:
[Client Portal Gateway limitations](https://ibkrcampus.com/campus/ibkr-api-page/cpapi-v1/#client-portal-gateway).

## Vercel Fit

Vercel documents Docker inside Sandbox, Amazon Linux 2023 with `sudo`, private
filesystems, and bounded runtime:

- [Run Docker containers inside Vercel Sandbox](https://vercel.com/changelog/run-docker-containers-inside-vercel-sandbox)
- [Sandbox documentation](https://vercel.com/docs/vercel-sandbox/)
- [Sandbox pricing and limits](https://vercel.com/docs/vercel-sandbox/pricing)

The scripts use a named persistent Sandbox and stop each session after the
command. Gateway containers, temporary password files, and prior audit files
are removed before the next command.

## Validation Evidence

The PoC has passed:

- Local tests and remote mock-worker reconciliation with same-intent reuse.
- Docker and third-party IB Gateway boot checks in disposable Sandboxes.
- Credentialed paper reconciliation and non-transmitting `whatIf`.
- Broker acceptance of bounded GTD and durable GTC AAPL brackets.
- Fresh-Sandbox recovery of broker-owned permanent order IDs.
- Same-intent reuse without a duplicate bracket.
- Broker-native GTD cleanup while no Sandbox was running.

## Production Gaps

Do not call this live-ready. Add a transactional intent store, account-level
limits, concurrency control, scheduled reconciliation, alerting, pinned image
digests, dependency review, and an authentication-exception runbook before
considering production use.

The operator workflow is intentionally recorded once, in
[`../AGENTS.md`](../AGENTS.md).
