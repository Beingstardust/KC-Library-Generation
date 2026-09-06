# 65. Running the verify suite on the secondary cluster when the primary cluster is saturated

The primary cluster reached a state where every partition was 228+ nodes allocated and `short` had 7 drained, 3
down and 23 more drained, so a two-minute verify run sat in `(Resources)` indefinitely. The secondary cluster had 11
idle nodes. This records how to use it, because two things about it are not obvious.

## The repo is not on the secondary cluster

Different filesystem. The secondary cluster is where the drafting runs happen (r3, r4) because those need its H100s
and its own ollama; the repo lives on the primary cluster's shared filesystem. So the suite runs against a **mirror**, and
the mirror is a snapshot: re-sync before every run or you are verifying stale code.

    ssh primary-cluster "cd $V && tar czf /tmp/repo_subset.tgz \
      --exclude=data --exclude=local_audits --exclude=.git \
      --exclude='*.pyc' --exclude=__pycache__ ."
    scp primary-cluster:/tmp/repo_subset.tgz secondary-cluster:~/
    ssh secondary-cluster "rm -rf ~/kcl_verify/src ~/kcl_verify/v3 ~/kcl_verify/steps ~/kcl_verify/config \
      && tar xzf ~/repo_subset.tgz -C ~/kcl_verify"

4.9 MB compressed, 32 MB expanded. Mirroring only `src` and `v3/verify` fails: the suite reads the
production probe under `steps/step_06_7_kc_draft_generation/` and the profiles under
`config/runtime/`, so it aborts partway with a FileNotFoundError - visibly, because the atexit
crash reporter added during the INT-11 audit prints the checks collected so far. Excluding `data`
and `local_audits` is what keeps it small; `local_audits` alone is 1.5 GB.

## The login node has packages the compute nodes do not

`pip install --user scipy` on the secondary cluster's login node succeeds and the import then fails on the compute
node. The reason is that the login node already carries scipy at `/usr/lib64/python3.9/
site-packages` as a system package, so the import that appeared to confirm the install was reading
a different copy entirely; the compute nodes run a different image and have neither.

Install into shared home with an explicit target and put it on the path:

    ssh secondary-cluster "python3 -m pip install --quiet --target ~/kcl_verify/pylibs scipy"
    ssh secondary-cluster "srun --partition=all --time=00:15:00 --mem=16G bash -c \
      'PYTHONPATH=\$HOME/kcl_verify/pylibs python3 \$HOME/kcl_verify/v3/verify/verify_pipeline_fixes.py'"

## It agrees with the primary cluster

The secondary cluster runs Python 3.9.25 against the primary cluster's 3.11.3 and the suite is version-clean: the INT-16-only
reconstruction reported **435 checks, 0 failed** on the secondary cluster, the number the primary cluster had reported for that
state, and the full tree reported **456**. So the secondary cluster is a usable second opinion as well as a
fallback, which is worth something on its own - a suite that only ever runs on one interpreter has
never had its version assumptions tested.

## What the secondary cluster is NOT for

The sabotage harness. It edits the working tree in place and restores it byte-exact, and the mirror
is a copy, so a sabotage run there would prove nothing about the repo. Sabotage stays on the primary cluster.
