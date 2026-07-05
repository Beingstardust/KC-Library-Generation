# Source-overlay acronym signal repair, 2026-05-10

This patch fixes a generic retrieval seam inconsistency. Step 5x source-overlay phrase generation can preserve uppercase acronym-like target labels, but direct-overlay conversion/scoring could later drop one-token target signals before local verification.

The repair is domain-agnostic and model-agnostic. It contains no course-specific terms, KC-specific branches, or model-specific behavior. It permits a one-token signal only when the original signal surface is uppercase, acronym-like, at least three characters, and not a generic stop/glue/broad-head term. Multi-token target signals are unchanged. Pack admission is not broadened directly.
