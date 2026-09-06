# Campaign accounting audit

Every count that appears in paper-facing documentation, re-derived independently from raw JSONL by
`reference_eval/audit_campaign_accounting.py`. Expected values are what the documentation asserts;
observed values are what the artifacts contain.

Run: 2026-09-02

```
quantity                                          expected  observed  status    note
----------------------------------------------------------------------------------------------------------------------
ablation rows                                         1113      1113  OK        
ablation unique eval_row_id                           1113      1113  OK        
ablation KCs                                           159       159  OK        
ablation arms                                            7         7  OK        
crossed rows                                          1137      1137  OK        
crossed cells                                            9         9  OK        
reference library KCs                                  159       159  OK        
review_action ACCEPT                                   117       117  OK        
review_action MINOR_EDIT                                10        10  OK        
review_action MAJOR_EDIT                                15        15  OK        
review_action REPLACE                                   10        10  OK        
review_action NO_REFERENCE                               7         7  OK        
support_state UNSUPPORTED                                7         7  OK        
support_state PARTIALLY_SUPPORTED                        2         2  OK        
support_state SUPPORTED                                150       150  OK        
KCs with a reference body                              152       152  OK        159 minus the 7 corpus-unsupported
nugget decomposition records                           152       152  OK        
KCs with nuggets (reference-scored)                    151       151  OK        1 structural decomposition failure: KC_CLF_NB_009
total nuggets                                         1185      1185  OK        
VITAL nuggets                                          475       475  OK        
nugget assignment judgements                          1057      1057  OK        151 scored KCs x 7 arms; the 8 unscored KCs have no nuggets to assign
context judgements (KC x evidence-config)              604       604  OK        
faithfulness records (incl. 1 superseded)             1114      1114  OK        1 blinding-exempt row re-judged; both records retained
faithfulness unique keys                              1113      1113  OK        
F-40 calibration calls                                 302       302  OK        
F-45 dilution calls                                    453       453  OK        
F-46 faith-dilution records                            145       145  OK        
pooled relevance judgements                           8246      8246  OK        
triage ablation                                       1113      1113  OK        
crossed groundedness                                  1137      1137  OK        
claim-extraction rows, ablation                       1113      1113  OK        
claim-extraction rows, crossed                        1137      1137  OK        
claims extracted, ablation                            7808      7808  OK        
claims extracted, crossed                                -      7975  OK        
matched claims, ablation (both judges)                7747      7747  OK        
matched claims, crossed (both judges)                 7914      7914  OK        
rerun-matched claims (denominator of 99.83%)          7610      7610  OK        996 drafts; 15 drafts excluded for claim-count mismatch
KCs scored by reference metrics                        151       151  OK        
----------------------------------------------------------------------------------------------------------------------
38 quantities checked, 0 mismatch(es)
```

## Correction made during this audit

One mismatch surfaced and it was in the **documentation**, not the data: nugget-assignment judgements
were expected to be 1113 (one per evaluation row) but are **1057**. That is correct — assignment runs
only for the 151 reference-scored KCs (151 x 7 arms = 1057); the 8 unscored KCs have no nuggets to
assign against. The expectation was wrong, and is now recorded as 1057.

## Reconciliations worth stating explicitly in the paper

| apparent discrepancy | explanation |
|---|---|
| 159 KCs but 151 scored | 7 KCs have no expert reference; 1 (`KC_CLF_NB_009`) fails decomposition structurally |
| 152 reference bodies but 152 decomposition records | the decomposition was attempted for all 152; one returned a structural failure |
| 1113 faithfulness rows but 1114 records | one blinding-exempt row was re-judged; **both** records are retained, the failed one superseded rather than deleted |
| 7808 ablation claims but 7747 matched | 61 claims sit in drafts where the two instruments disagreed on claim count and were excluded from the matched comparison |
| 99.83% over 7610, not 7808 | the rerun control excludes 15 drafts whose re-decomposition changed the claim count |
| 8246 pooled judgements from 159 KCs | union of top-20 across four distinct retrieval configurations, mean ~52 per KC |

All 38 quantities now reconcile.
