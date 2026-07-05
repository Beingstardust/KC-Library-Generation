# Step 6.x Alias Refresh Rule

## Purpose
Prevent accidental consumption of stale Step 6.6 / Step 6.7 aliases after exploratory slice runs.

## Rule
Before any Step 6.8 run or any alias-dependent Step 6.x run:
1. inspect current_step_artifacts.status.json
2. inspect the specific alias JSON being consumed
3. if the alias target is not the intended set_id, refresh aliases intentionally
4. record the exact set_id in operator notes or audit output

## Important
Do not assume the latest exploratory run automatically becomes the active alias target you intend to use.
