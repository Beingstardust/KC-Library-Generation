# Step 6.7 Generic Drafting Policy Spec v1

## Purpose
This file defines the generic drafting policy for Step 6.7 so that the KC drafting path remains reusable for user-supplied course materials and imperfect hierarchy seeds, instead of turning into a Data Mining-specific patch stack.

## Scope
This policy governs only Step 6.7 drafting support selection and field assembly behavior.
It does not change:
- Step 6.6 overlay construction
- Step 6.8 packetization logic
- review workflow
- audit ingestion/resolution
- reviewed-library assembly
- runtime packaging

## Project intent
The pipeline must support:
- user course materials as source corpus
- imperfect hierarchy seed as starting topical scaffold
- leaf nodes as candidate KCs
- internal nodes as topics / broader topics
- machine drafting before review
- expert approve / edit / reject
- approved KCs into frozen library
- rejected / unresolved into sandbox
- runtime packaging only from reviewed frozen library

## Non-negotiables
1. No unconstrained freeform KC generation.
2. Every drafted field must be grounded in extracted evidence or remain blank/held.
3. No source-unit-name logic in core drafting policy.
4. No corpus-specific doc-id guards in final Step 6.7 policy.
5. Honest abstention is better than wrong drafting support.
6. Human review remains mandatory before frozen-library entry.

## Generic row-level policy features

### Anchor strength
A row may have:
- `strong`
- `weak`
- `none`

A row is `strong` when at least one of these is true:
- exact canonical concept-name mention
- exact alias mention
- exact formula lhs anchor for the target concept
- source-block-level definitional anchor tied to the target concept

A row is `weak` when the concept is only indirectly implied by seed keywords or nearby context.

A row is `none` when there is no reliable concept-specific anchor.

### Definition surface type
Each row must be classified as one of:
- `prose_definition`
- `named_formula`
- `theorem_statement`
- `formula_backed_explanatory_clause`
- `anchored_descriptive_clause`
- `generic_context`
- `formula_lead_in`
- `heading`
- `question`
- `mixed_concept_list`

### Background drift class
Each row must be classified as:
- `none`
- `generic_recap`
- `statistical_test_background`
- `train_test_setup_background`
- `neighboring_concept_list`
- `algorithm_family_background`
- `generic_evaluation_background`

### Concept-mix risk
Each row must be classified as:
- `single_concept`
- `neighboring_concept_bleed`
- `mixed_concept_list`

## Hard blocks
A row cannot provide drafting support if any of these are true:
- question-like
- heading or bare heading
- formula lead-in without explanatory completion
- high contamination
- concept_mix_risk = mixed_concept_list
- background_drift_class != none and anchor_strength = none

## Soft penalties
A row should be penalized, not always blocked, when:
- anchor_strength = weak
- background_drift_class != none and anchor_strength = weak
- concept_mix_risk = neighboring_concept_bleed
- generic_context surface without concept-specific definitional cue

## Allowed positive drafting support
A row may support drafting only if:
- it survives hard blocks
- and it is one of:
  - prose_definition with strong anchor
  - named_formula with strong anchor
  - theorem_statement with strong anchor
  - formula_backed_explanatory_clause with strong anchor
  - anchored_descriptive_clause with strong anchor

## Field assembly rules

### Definition full candidate
Allowed only from positive drafting support rows.
Never from:
- heading
- question
- generic recap
- mixed concept list
- formula lead-in only

### Definition short candidate
May be extracted only from the chosen definition-support row.
No shortest-fragment fallback.
No heading fallback.

### Scope candidate
May be drawn from already-selected grounded support rows when:
- provenance is valid
- contamination is not high
- the row is not heading / question / formula lead-in
- the row contains explicit use / applicability / scope cues
If not, leave blank and mark intentionally blank or abstained as appropriate.

## Current known failure cluster
The current generic policy is still too strict for parts of the evaluation/model-comparison family.
The failure is not allowed to be solved with Data Mining-specific source-unit-name guards.

## Current next calibration target
Calibrate anchor_strength + background_drift_class + concept_mix_risk so that:
- bad evaluation drift stays blocked
- genuinely concept-anchored evaluation definitions can still survive

## Scale gate for full-course drafting
Do not run full-course drafting until all of the following are true:
1. The affected evaluation-family subset no longer relies on source-unit-name guards.
2. The subset produces cleaner outputs without collapsing into near-total holds.
3. The remaining held cases look honestly held, not suppressed by over-strict generic policy.
4. No new corpus-specific Step 6.7 guards were introduced.

## Reminder
The final operational endpoint is not machine drafts.
The final operational endpoint is:
reviewed frozen library -> runtime packaging -> retrieval-ready KC library.