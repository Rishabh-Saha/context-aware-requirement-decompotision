# Decision: Layer 4 calibration outcome

Status: DECIDED (2026-08-14)
Applies to: generation run 20260814T033139Z

## Outcome
Layer 4 researcher-vs-judge calibration on the 20-pair blind sample:
- Overall (gate metric, researcher vs judge reconciled winner): Cohen's kappa = 0.56, n = 19,
  95% CI [0.19, 0.94]. Pre-registered threshold is 0.6.
- Result: FAIL. The judge did not reach the substantial-agreement bar.

Per-criterion kappa (each on its own n, cells dropped never imputed): actionability 0.67,
completeness 0.61, clarity 0.81, project_specificity 0.56, granularity 0.32. Pooled criteria 0.60.
Raw overall agreement was high (0.84); kappa is lower because chance agreement on a forced binary
choice is ~0.5.

## Consequence (follows the pre-registered plan, proposal Section 7.4)
- Layer 3 (pairwise LLM judge) is NOT validated as a primary quality signal for this run.
- Layer 3 is therefore reported DESCRIPTIVELY only.
- Primary conclusions rest on Layer 1 (structural, diagnostic) and Layer 2 (file grounding).
- This was the pre-committed contingency, not a post-hoc reaction to the result.

## What still stands
- Layer 2: RAG significantly reduces file hallucination (~70% -> ~50%, paired test). Primary finding.
- Layer 3 (descriptive): judge preferred neither RAG nor vanilla on quality (SQ2 ~44% full_rag),
  and preferred both LLM conditions over the human reference at ~100% (SQ3). Combined with the
  failed calibration and the SQ3 genre/format asymmetry, this indicates the judge tracks format
  more than substance. Reported as a methodological finding about LLM-as-judge, not as validated
  quality evidence.
- The calibration failure is itself a result: at this task and scale, the LLM judge could not be
  validated against human judgment to the pre-registered standard.

## Limitations to record in the write-up
- Single-annotator calibration (researcher only); no inter-annotator agreement. Known limitation
  from the proposal.
- n = 20 makes kappa unstable: a few pairs move it substantially and the 95% CI is wide. State
  this explicitly when reporting the kappa.

## Integrity note
The reported kappa is from the single blind human rating pass. An alternative sheet produced by
having an LLM fill the ratings was discarded and NOT used: an LLM rating another LLM's outputs does
not constitute independent human calibration and cannot substitute for it.