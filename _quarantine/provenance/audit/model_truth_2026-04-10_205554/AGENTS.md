# AGENTS.md

This file is the durable repo-local copy of the session instructions that were previously only present in chat.

## Skills

A skill is a focused set of instructions stored in a `SKILL.md` file and used when a task clearly matches that workflow.

### Available skills

- `skill-creator`: create or update a Codex skill when the user wants to extend Codex with reusable knowledge, workflows, or tool integrations.
- `skill-installer`: list or install Codex skills from the curated catalog or from another repository path.

### How to use skills

- Discovery: use the active session skill list first.
- Trigger rules: if the user names a skill or the task clearly matches one, use it for that turn.
- Missing or blocked: if a named skill is unavailable, say so briefly and continue with the best fallback.
- Progressive disclosure: read only the specific `SKILL.md` sections needed for the current task.
- Path resolution: resolve skill-relative paths from the skill directory first.
- Reuse: prefer skill scripts, templates, and assets over retyping large blocks manually.
- Context hygiene: avoid bulk-loading references; open only the files needed to complete the task.
- Coordination: if multiple skills apply, use the minimal set and state the order.
- Safety: if a skill cannot be applied cleanly, report the issue and continue with a defensible fallback.

## Repo Changelog

- Keep the repo-root `CHANGELOG.md` updated for every repo change made during a session.
- Add a short dated entry describing what changed and where.
- Treat `CHANGELOG.md` as the durable running log going forward; older one-off reports remain historical reference only.
