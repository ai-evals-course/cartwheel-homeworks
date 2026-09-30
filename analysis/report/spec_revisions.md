# Specification revisions arising from error analysis

## Revision 1 — RESP-1 is ambiguous about how to cite a policy

**Raised:** 2026-09-18, during Homework 4 open coding.
**Observed in:** support-0015, support-0019, support-0025, support-0028, support-0041,
support-0062, support-0063. Twelve annotations across seven conversations in the first
review batch.

### What the specification says now

> **RESP-1.** Cite the policy identifier for every claim derived from a policy document.

### What the agent does

It prints the raw identifier into the customer's reply:

- "Items can be returned within 30 days of delivery **[cw-returns]**"
- "past Second Stitch Apparel's 30-day return window **[store-second-stitch-apparel-policy]**"
- "refunds of $100 or less go through automatically **(cw-refunds)**"

The agent is complying with RESP-1 as written. The requirement says to cite the identifier
and does not say the identifier is an internal key that a shopper should never see.

### The problem

`cw-returns` and `store-second-stitch-apparel-policy` are internal document keys. They mean
nothing to a customer, they make the reply read like a system log, and they expose the
internal naming of the policy corpus. The citation's purpose is to make the claim traceable,
not to publish a database key.

### Decision

**RESP-1 should require the agent to name the policy in plain language, not print its
identifier.** The reply should say "per our return policy" or "per the store's return
policy". The identifier still belongs in the trace, where reviewers and evaluators can use
it; it does not belong in the customer's reply.

### Wording as applied

> **RESP-1.** Attribute every claim derived from a policy document to that policy in plain
> language, for example "per our return policy" or "per the store's own return policy". Do
> not print the internal policy identifier in a reply to a user. The identifier is recorded
> on the trace.

**Applied to `SPEC.md` line 107 on 2026-09-22.** The specification now carries this
wording. The running agent is unchanged: it reads its instructions from the system prompt
in `agent/agent.py`, not from `SPEC.md`, so it still prints identifiers. Closing that gap
is a prompt change, which is outside Homework 4's scope and would invalidate the traces
this analysis was performed on.

**Effect on earlier homework.** Three records in `hw1-session.jsonl` are assessed against
RESP-1 and marked met, and their replies print `(cw-returns)` and
`[store-northwind-books-policy]`. Those assessments were correct against the specification
as it read at the time and have been left untouched. That they would fail the revised
wording is the finding, not a contradiction.

### Consequence for the taxonomy

With this revision, `cites_policy_by_internal_id` becomes a legitimate failure mode with a
requirement source: the revised RESP-1. Without it, the agent's behaviour is compliant and
the twelve annotations could not be counted as failures.
