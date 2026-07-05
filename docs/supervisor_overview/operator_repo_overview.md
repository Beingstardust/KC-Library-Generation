# Supervisor Overview

This repo is now a clean operator repo rather than a preserved history tree.

It starts empty of runtime state, keeps Topic Library and KC Library separate, requires human
approval before usability, and prepares the project for:

- fresh offline runs
- later approved-only freezing and indexing
- later UI wrapping
- a future textbook-scale HPC execution path

The research-era step tree is retained internally for control-flow preservation, but the public
surface is now the operator scripts and configs under `scripts/` and `configs/`.
