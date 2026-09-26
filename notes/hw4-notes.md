# HW4 notes for teaching

Concrete case studies from building the review interface and starting open
coding. See [concepts.md](concepts.md) for the generic
generalization-failure-vs-tooling-gap framing this exercises, and its "Two
error-discovery methods are complementary, not either/or" entry for why Part
C (Raindrop Workshop) follows Part B (open coding) instead of replacing it.

## Case study: a failure with no available fix at the model layer

Scenario `support-0190` (and the pilot's `pilot-0023`): order 8003 is
recorded under store 1 ("Blue Heron Ceramics"), but its `product_id` (553)
actually belongs to store 14, a product titled "Portable Jam Trio" — a
genuine data inconsistency, not a hallucination. The agent confidently
described the order as a Blue Heron Ceramics purchase and walked through
the standard return policy, never noticing the mismatch.

The natural next question — "which tool should it have called to catch
this?" — has a real, checkable answer: none. `get_order` returns
`product_id` as a bare number plus the *order's own* `store_id`/
`store_name`; it never returns the product's title or the product's own
store. `search_products` takes a text query matched against title/
description, with no way to look up one exact product by id. No
combination of available tool calls could have surfaced the fact needed
to catch this — so this is a specification/tooling gap (a missing
`get_product(product_id)`-style lookup), not a generalization failure a
prompt edit could fix.

Practical habit worth keeping: before assuming a trace failure is a model
problem, actually read the docstrings/return shape of every tool the agent
had access to and check whether the needed fact was reachable at all.

## Case study: "didn't guess" is not the same as "handled it well"

Scenario `support-0226`: shopper says "check on my order, I don't remember
the number." Expected behavior was just "don't guess a specific order."
The agent technically satisfied that — it never picked one order and
acted on it — but it did so by dumping the shopper's entire order history
(all 20 records, full detail) rather than asking a clarifying question or
narrowing down first. Passing the original check can still leave a real,
separate problem on the table; open coding one trace for one thing doesn't
mean there's nothing else worth a second note.

## Case study: a leaked placeholder invalidated five scenarios

Scenarios `support-0201` through `support-0205` (all `dq-product-missing-title`)
all read the same broken way, e.g. "How much is the **that item (empty title
in the catalog)** from Blue Heron Ceramics?" The generator's fallback text for
a product with no title — `"that item (empty title in the catalog)"`, meant as
an internal placeholder — got substituted straight into the simulated
customer's own message instead of staying out of it. No real shopper would
ever say "empty title in the catalog"; that phrase describes our own
data-quality seeding, not something a customer could know or say.

Once the input itself is incoherent, the response can't be fairly judged
against the original intent ("don't invent a product name"). The agent asking
for a link/SKU/screenshot reads as a reasonable reaction to a garbled message,
not as evidence of good or bad handling of a missing title. Treated as
invalid/excluded rather than pass or fail for all five.

This is the input-side mirror of the leak `SKILL.md` warns about on the
output side (hidden internal facts belong out of generation prompts) — worth
a dedicated check when building a scenario generator: grep the finished
`opening_message` values for any literal fallback/placeholder strings before
trusting the set.

## Case study: an escalation channel offered for the wrong reason

Scenario `pilot-0027`: an order correctly denied a refund because a
store's stricter return-window override had elapsed. The agent then
offered to open a *dispute* instead. Disputes (`ESC-3`, `cw-disputes`) are
for things like "never arrived" or "wrong item" — not a generic escape
hatch for "you're past the window and want an exception." Worth watching
for this pattern generally: an agent correctly enforcing one rule, then
undermining it by routing the user toward an unrelated mechanism that
happens to still be available.
