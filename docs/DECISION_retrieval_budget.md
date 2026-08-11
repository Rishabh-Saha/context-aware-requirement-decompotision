# Decision: per-type retrieval budget

Status: DECIDED — Option B (Rishabh, 2026-08-11)

## Problem
Global top-k (top-8) retrieval over a single fused similarity pool lets the context type most
similar to the query monopolise the slots. The query is a Jira requirement, so past_tickets
dominates. Observed on the sanity index:
- PIG-692 full_rag: 8/8 past_tickets (design_docs, conventions, summaries = 0)
- PIG-704 full_rag: 6 past_tickets + 2 design_docs (conventions, summaries = 0)

design_documents is fully populated (1451 chunks), so this is relevance domination, not a
population gap.

## Why it matters
If a context type never enters full_rag, its leave-one-out condition removes nothing, so its
ablation arm measures a null effect by construction rather than by finding. Under global top-k,
three of four SQ1 arms (design_docs, conventions, summaries) collapse. Only past_tickets is
measurable. This guts SQ1.

## Options
A. Per-type quota, keep the fused pool. Retrieve top-N per active type (e.g. 2 each), fuse within
   that budget. Smallest change; keeps hybrid + RRF. Quota is a patch on top of pooling.
B. Per-type retrieval, ablation at assembly. Each context type retrieved independently with its
   own top-k; prompt has one labelled block per type; leave-one-out omits that block. Cleanest map
   to "marginal value of each context type"; easiest to defend. RRF fuses dense+lexical within a
   type rather than across types. Furthest from the proposal's "global top-k with RRF" wording.

## Deviation note
Both options deviate from the proposal (Section 7.2: global top-8 with RRF). 


## Write-up framing (either option)
"Global top-k retrieval allowed query-similar context (past tickets) to monopolise the retrieved
set, collapsing three of four ablation arms. Retrieval was therefore moved to per-type budgets so
each context type is represented and each leave-one-out removes a measurable block." This is a
finding about the pipeline, reported as such, not a silent fix.

## Decision
Chosen: Option B — per-type retrieval, ablation at assembly (Rishabh, 2026-08-11).

Rationale: each context type gets its own fixed budget and its own labelled block, so full_rag is
represented by all four types rather than monopolised by past_tickets. This is expected to produce
more accurate, better-grounded full_rag user stories, and it makes every leave-one-out arm remove a
measurable block, keeping SQ1 answerable.

Budget: 2 chunks per type (8 total), preserving the original top-8 prompt size.
RRF: fuses dense + lexical within each type, not across types.