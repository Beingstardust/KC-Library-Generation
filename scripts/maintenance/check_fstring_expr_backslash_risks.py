from pathlib import Path
import sys

TARGETS = [
    Path("src/kc_l/utils/kc_step67_model_drafting.py"),
    Path("src/kc_l/kc_drafting/heuristic_core.py"),
]

bad = []

for path in TARGETS:
    if not path.exists():
        continue
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if ("f\"" in s or "f'" in s) and "re.sub(" in s:
            bad.append((str(path), lineno, s))

if bad:
    print("FSTRING_EXPR_BACKSLASH_RISK_FOUND")
    for path, lineno, line in bad:
        print(f"{path}:{lineno}: {line}")
    sys.exit(1)

print("FSTRING_EXPR_BACKSLASH_RISK_OK")
