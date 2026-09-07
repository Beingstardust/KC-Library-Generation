#!/bin/bash
# Isolated-environment wrapper for the DOS-RAG comparator. Source this before running any
# comparator script. Installs nothing into kc_l_v2's own venv - new packages
# (nltk/tiktoken/openai/tenacity/...) live in a separate --target directory; heavy already-vetted
# shared deps (torch/sentence-transformers/scipy/numpy) are reused via PYTHONPATH from the
# existing kc_l_v2 venv's site-packages, not reinstalled (avoids a multi-GB re-download the
# no-internet login node could not do anyway). See 04_ENVIRONMENT_SETUP.md.
set -u
MIR=/path/to/kc_l
COMPARATOR_DIR=$MIR/v3/comparators/dos_rag

export LD_LIBRARY_PATH=/path/to/python/lib
export PYTHONPATH=/path/to/pylibs/dos_rag_comparator_deps:/path/to/venv/lib/python3.11/site-packages
export NLTK_DATA=$COMPARATOR_DIR/nltk_data
export TIKTOKEN_CACHE_DIR=$COMPARATOR_DIR/tiktoken_cache
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PY=/path/to/venv/bin/python

echo "DOS-RAG comparator environment ready."
echo "  PY=$PY"
echo "  PYTHONPATH=$PYTHONPATH"
echo "  NLTK_DATA=$NLTK_DATA"
echo "  TIKTOKEN_CACHE_DIR=$TIKTOKEN_CACHE_DIR"
