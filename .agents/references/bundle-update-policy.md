At the start of the first Steam Purchase Advisor workflow in the current conversation or agent run, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/check_update.py
```

Do not run the checker again if an update check has already occurred in the current context, including when a sibling Steam Purchase Advisor skill performed the check before handing off this workflow.

The update check is informational and must never block or alter the requested Steam workflow. For `up_to_date`, `ahead`, or `unavailable`, continue silently. Do not retry an unavailable check.

If the checker reports a local bundle error, continue the requested workflow and follow the bundled-script failure rules. Never create, repair, or replace update-check files during normal skill execution.

If the checker reports `update_available`, remember the installed and latest bundle versions and complete the current workflow using the currently loaded skill instructions. Do not inspect Git state, update files, or interrupt the workflow solely to report the update.

After the substantive response, state that a Steam Purchase Advisor bundle update is available, show the installed and latest versions, state that the current task used the installed version, and ask whether the user wants the local skill bundle updated. Do not guess or print an update command before inspecting the installation method.

Never modify skill or repository files merely because an update is available.

When the user explicitly approves an available update, inspect the local state without modifying files.

For a Git installation, identify a configured remote that points to the canonical `icue/SteamPurchaseAdvisor` repository. Require that the active branch is exactly `main`, no active Git operation is present, no tracked working-tree changes exist, no staged changes exist, and history can fast-forward from the current `main` HEAD to the fetched canonical `main`. Ignored `config.json` does not block an update. Ensure only standard `git fetch` and `git merge --ff-only` are used; do not use wrapper tools like `gh`.

Only update a verified canonical Git installation with a standard fast-forward-only operation. Never stash, reset, restore, clean, discard, rebase, force, change branches, rewrite remotes, or create a merge commit to perform an update. Local-only commits, divergent history, detached HEAD, non-main branch, active Git operations, tracked modifications, staged changes, or missing canonical provenance block an agent-performed Git update.

If no safe supported update method is available, leave the installation unchanged and explain the concise reason.

After a successful update, validate the newly installed repository-level `VERSION`, report the actual installed version, and stop the Steam Purchase Advisor workflow. Ask the user to start a **new session** (rather than just repeating the request) so the client can load the updated skill instructions into a clean context. Never continue the current Steam workflow using repository files changed by the update.
