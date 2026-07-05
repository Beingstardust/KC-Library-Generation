# KC_L v2 pipeline control flow

The orchestrator models the whole pipeline from input ingestion onward. It is not a Step6.8-only wrapper.

Current endpoint: `step_06_8_review_packet_emission`.

Terminal status: not terminal. The pipeline continues to expert review, frozen reviewed library, runtime library, and downstream segmentation/evaluation.

