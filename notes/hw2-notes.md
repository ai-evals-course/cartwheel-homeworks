# HW2 notes for teaching

Concrete case studies and sequencing ideas from doing HW2. See
[concepts.md](concepts.md) for the generic tracing/observability concepts
these exercise (trace/span, gen_ai.* vs application fields, the
OTel/OpenLLMetry/Langfuse stack, prompt-version hashing, max_turns, and the
request/trace/span/session distinctions).

## Case study: a required span attribute that wasn't required

The handout's root-span attribute list didn't include a session identifier
— only role/user/prompt-version/scenario-id. That means, out of the box,
there's no stamped link from a trace back to which session produced it,
only to which user/role. We added a `cartwheel.session_id` attribute
ourselves once this came up in conversation.

Teaching point: a good moment to have students notice a gap themselves
("how would you find every trace belonging to one session?") before
showing them the fix, then discuss it as a "the spec gives you a floor,
not a ceiling" moment — nothing stops you from recording more than a
handout/spec requires when it closes a real gap, as long as the required
fields are still present too.

## Case study: a stale pinned Docker image blocking local setup

Starting the local Langfuse stack failed at the `minio` container with a
Docker Hub "pull access denied" error, unrelated to any homework code. The
image (`minio/minio:latest`) had stopped receiving free Docker Hub
distribution; switching to MinIO's Quay-hosted mirror
(`quay.io/minio/minio:latest`) fixed it. See
[concepts.md](concepts.md#practical-gotcha-self-hosted-docker-images-going-stale)
for the general pattern this illustrates.

## Good teaching sequence

1. Show a span tree in a trace viewer first (concrete, visual), *then*
   explain trace/span in the abstract. Abstract-first tends to lose
   non-engineers.
2. Contrast automatic vendor fields (`gen_ai.*`) vs. hand-added
   application fields (`cartwheel.*`) side by side on the same tool-call
   span — makes the "why do we even need instrumentation code" question
   answer itself.
3. The token/session split (Part B) is a good moment to discuss why
   authentication has to live at a "choke point" (the endpoint) rather
   than be inferred from conversation content — ties directly to later
   discussion of attacks on this same shape (a server-issued credential
   tools trust).
