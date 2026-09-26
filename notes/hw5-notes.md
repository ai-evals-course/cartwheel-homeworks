# HW5 notes for teaching

Concrete case studies from building and evaluating an LLM judge for
`mishandles_vague_requests`. See [concepts.md](concepts.md) for the generic
framing each of these exercises: prompt iteration overfitting to dev,
held-out test discipline, confidence intervals in metric comparisons, and
cache-masked retries.

## Case study: the judge that "stopped watching" after a good opening

Scenario `live-46db4e4`: a shopper asks for anything "pink" that fits a
small room. The agent's opening move is genuinely good — it asks a
specific, tool-actionable clarifying question. Then, after the customer
just says "anything pink," it runs roughly 30 speculative search variants
back to back (all zero results) and closes by asserting "even if the color
isn't in the title, we can often find the right style keywords" — implying
pink variants might exist, with nothing in any tool result supporting that.

The v0 judge prompt scored this **Pass**, and its own critique explained
why: "this technically does not break the initial PASS... the initial
handling of the vague request remains strong enough to maintain a PASS
status overall." The judge had anchored on the opening turn and treated a
good first move as if it locked in the verdict for the whole conversation,
explicitly waving off both the 30-call search spiral and the unsupported
closing claim. Nothing in the v0 prompt told it a later turn could flip an
earlier-good response to Fail — a purely structural gap, not a case the
judge was reasoning about incorrectly given what it was told.

## Case study: an exclusion clause that stated the rule without enforcing it

v1's prompt added an escalation exclusion: if the agent correctly escalates
per policy (a dispute, an account change), that's a Pass "even if the
agent never asks the customer anything first." Reasonable-sounding
sentence — and the judge kept failing traces anyway, with critiques like
"the agent correctly escalated... however, it did not ask a clarifying
question first" before concluding Fail. The exclusion was worded as
context ("asking isn't required here") rather than as a hard stop, so the
model kept applying the general clarifying-question rule on top of it
instead of exiting early. v2 rewrote it as an explicit gate: "if escalation
is present and appropriate, stop evaluating and return Pass" — naming the
exact wrong-reasoning pattern to avoid ("do not write a critique that
says X, then conclude Fail") fixed it. Worth remembering generally: a rule
phrased as "you don't have to do X" can still get overridden by a strongly
-stated general instruction elsewhere in the same prompt; a rule phrased as
"stop and return this verdict" is much harder to talk past.

## Case study: fixing dev's biggest problem can create a new one

v1 fixed v0's TNR problem (missed failures) by telling the judge to weigh
the whole conversation, not just the opening. v2's dev batch then showed a
fresh failure mode: the judge began requiring a clarifying question even
when the agent's own tool lookup had *already* fully resolved the
ambiguity (e.g., "every one of your orders is already shipped, so nothing
is cancellable regardless of which one you meant" — there's no real
question left to ask). Each revision solved what it was aimed at and
introduced a new, previously-invisible edge at the boundary it moved. This
is a normal shape for iterative prompt refinement, not a sign something was
done wrong — it's part of why the handout caps revisions rather than
promising convergence.

## Case study: one line added to a list didn't change the judge's behavior

v2 explicitly added "shopper name" / "customer name" to the list of things
no tool can accept, motivated by a disagreement (`hw5-ncq-33`) where the
agent offered it as a fallback alongside a real order-ID ask. The next dev
run still scored that exact trace Pass, with the critique praising the
"shopper name" option as "further indicating the agent's understanding of
the vagueness." A single list item, added without a worked example showing
it in context, wasn't enough signal to outweigh the otherwise-good parts of
that response. The pattern that *did* generalize (Example 4, the same rule
demonstrated end-to-end in a full conversation) suggests examples carry
more weight than list items for this kind of nuanced, easy-to-rationalize-
away rule.
