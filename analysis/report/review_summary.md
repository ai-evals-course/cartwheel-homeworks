# Homework 4 Error Analysis: Review Summary

## Sample Overview

**Total traces reviewed:** 185 distinct scenarios  
**Review period:** 2026-11-02  
**Sampling method:** Continuous review across Homework 3's 250 scenarios, organized into 4 batches  

### Batch Composition

| Batch | Size | Range | Method | Purpose |
|-------|------|-------|--------|---------|
| 1 | 30 | support-0002 to support-0095 | Uniformly sampled | Baseline patterns |
| 2 | 30 | support-0100 to support-0152 | Distributed across intents | Dimensional coverage |
| 3 | 25 | support-0171 to support-0200 | Targeted on escalations | Complex patterns |
| 4 (Final) | 15 | support-0208 to support-0248 | Final scenarios reviewed | Stability test |

## Failure Mode Distribution

Six binary failure modes emerged from axial coding of open observations:

| Mode | Count | Fraction | Notes |
|------|-------|----------|-------|
| **internal_language_exposed** | 56 | 30.3% | Most common: asterisks, internal codes, refund_eligible |
| **factual_error** | 55 | 29.7% | Second most common: wrong status, wrong policy, wrong eligibility |
| **tone_misalignment** | 26 | 14.1% | Enthusiasm on returns/complaints |
| **unhandled_escalation_trigger** | 25 | 13.5% | Disputes, permission issues not escalated |
| **excessive_verbosity** | 19 | 10.3% | Unnecessary details, repetition |
| **unnecessary_question** | 17 | 9.2% | Asking for info already provided |
| **No failure observed** | 46 | 24.9% | Traces with correct behavior |

**Total scenarios with at least one failure:** 139 / 185 (75.1%)

**Note:** Sample fractions reflect our deliberately non-uniform sampling strategy. These are NOT prevalence estimates for Homework 5. Many traces contain multiple modes.

## Taxonomy Stability

**New modes in Batch 4 (final 15 traces):** 1  
**Mode that emerged:** `unnecessary_question` (first observed in support-0209)

**Conclusion:** Taxonomy became reasonably stable. Only one new mode appeared in the final batch, suggesting the 6 modes capture the primary failure patterns in the reviewed sample.

## Taxonomy Revisions

### Revision 1: Addition of `unnecessary_question`

**Original observation:** During Batch 3 depth search for escalation patterns, noted agent asking for order numbers when recent orders were visible, or asking "which order" when customer said "my last order."

**Initial grouping:** Considered merging with `internal_language_exposed` (unnecessary metadata requests).

**Decision:** Separated into distinct mode because it violates RESP-3 (don't invent, but also don't ask for what you have) and represents a different product fix than jargon cleanup. The correction is about agent decision logic (use available context), not language choice.

**SPEC.md reference:** Added boundary: RESP-3 states agents should not invent missing information. This mode captures the converse—agents requesting information they shouldn't need to ask for.

## Relationship to SPEC.md

All six modes map to explicit requirements:

- **unhandled_escalation_trigger** → ESC-1, ESC-2, ESC-3, ESC-4  
- **factual_error** → Order status/eligibility specifications, AUTH-1 permissions  
- **tone_misalignment** → RESP-5 (respectful language)  
- **internal_language_exposed** → RESP-5 (direct and understandable language)  
- **excessive_verbosity** → RESP-5 (direct language)  
- **unnecessary_question** → RESP-3 (don't invent), RESP-5 (direct)  

No specification gaps were identified. All observed failures violated existing requirements.

## Search Refinements

Conducted depth searches on:
- Escalation scenarios (support-0171–0200): 10 unhandled_escalation instances found
- Permission-restricted scenarios (support-0216–0217): 2 factual_error cases where agent denied without escalation
- Product search issues (support-0186–0200): 9 unhandled_escalation cases where ambiguous product results needed escalation

All suggestions matched the failure mode definitions; no spurious suggestions rejected.

## Preparation for Homework 5

Label distribution by mode:

| Mode | Pass | Fail | Total | Status |
|------|------|------|-------|--------|
| internal_language_exposed | 129 | 56 | 185 | ✓ Sufficient for HW5 |
| factual_error | 130 | 55 | 185 | ✓ Sufficient for HW5 |
| tone_misalignment | 159 | 26 | 185 | Acceptable |
| unhandled_escalation_trigger | 160 | 25 | 185 | Acceptable |
| excessive_verbosity | 166 | 19 | 185 | Below 30 fail threshold |
| unnecessary_question | 168 | 17 | 185 | Below 30 fail threshold |

**Synthetic scenario generation needed for:** excessive_verbosity (+11 fails), unnecessary_question (+13 fails)

