---
name: land
description: >-
  Land requested PocketFed changes on samcday/pocketfed main through a GitHub pull request after
  green GitHub Actions plus CodeRabbit and Codex reviews of the PR head. Run only when a person
  invokes /land or Land Changes; not for review, preparation, passing checks, or skill setup.
disable-model-invocation: true
metadata:
  delta-action: land
---

# Land PocketFed changes

Invoking this skill asks to land the named changes, by default this thread's; honor narrower asks
such as "open the PR only". Merge only when every gate passes on one PR head; green CI, tests and
bot reviews are conditions, never authorization. Never waive a gate: if one can't pass in scope or
is unavailable, stop and report the PR URL, head SHA and blocker. GitHub Actions is the build gate;
full local image builds are optional. Sam runs Delta `/review` himself; don't start one.

## 1. Publish a focused PR

1. Inspect `git --no-optional-locks status --short --branch`, `git remote -v` and the diff. Ask if
   it's unclear which edits belong to the request; if nothing remains to land, say so and stop.
2. Target `samcday/pocketfed` `main`. Push only to the remote whose URL is that GitHub repository,
   never `local`; stop if none exists. Pass `-R samcday/pocketfed` to `gh pr`/`gh run` commands.
3. Commit on a topic branch; never commit to or force-push `main`. Stage only the requested paths or
   hunks, new files included; keep unrelated edits (no `git add -A`, `reset --hard`, `restore`).
4. Rebase onto freshly fetched `<remote>/main`; push (`--force-with-lease` if rewriting the branch).
   Open (`gh pr create -R samcday/pocketfed --base main --head <branch>`, stating problem, change,
   checks) or reuse the PR, and `gh pr ready` it if it is a draft.

## 2. Gate the current head (any new head restarts this section)

Set `HEAD_SHA` from `gh pr view <pr> -R samcday/pocketfed --json headRefOid`.

1. Post two separate PR comments, `@coderabbitai review` and `@codex review`, with `gh pr comment`.
2. Wait with `gh pr checks <pr> -R samcday/pocketfed --watch`. Then the latest run of each workflow
   in `gh run list -R samcday/pocketfed --commit <HEAD_SHA> --json workflowName,conclusion,url` must
   be `success`; if no run for `HEAD_SHA` appears within 10 minutes, CI is unavailable.
3. CodeRabbit: its `CodeRabbit` check/status on `HEAD_SHA` must read `Review completed`.
   `Review skipped`, rate limits, pauses and errors mean no review.
4. Codex: `chatgpt-codex-connector[bot]` must post a review with `commit_id` `HEAD_SHA` or a
   "Didn't find any major issues" comment whose **Reviewed commit** abbreviates `HEAD_SHA`. Either
   bot lacking such a result 30 minutes after its request is unavailable; reactions don't count.
5. Read every finding (`gh api --paginate` on `repos/samcday/pocketfed/pulls/<pr>/reviews`,
   `.../pulls/<pr>/comments`, `.../issues/<pr>/comments`), nitpick and outside-diff sections too.
   Fix valid in-scope findings in a new commit or reply with evidence; ask before scope changes. A
   human `CHANGES_REQUESTED` review blocks. Never clear a gate with `@coderabbitai resolve`/`approve`.

## 3. Merge and report

1. `git fetch <remote> main`. If `<remote>/main` isn't an ancestor of `HEAD_SHA`, rebase, run
   `git push --force-with-lease=<branch>:<HEAD_SHA> <remote> <branch>`, and restart section 2.
2. `gh pr merge <pr> -R samcday/pocketfed --rebase --match-head-commit <HEAD_SHA>`; PocketFed only
   enables rebase merges. Never use `--admin`; if the merge is refused, return to step 1.
3. Confirm `gh pr view <pr> -R samcday/pocketfed --json state,mergeCommit,url` shows `MERGED`, then
   fetch and check `git merge-base --is-ancestor <mergeCommit> <remote>/main`. If `main` moved
   mid-merge (`git diff --quiet <HEAD_SHA> <mergeCommit>` fails), await and report its push CI.
4. Report the PR URL, `mergeCommit` and GHA run URL(s) for `HEAD_SHA`. For a final landed or failed
   result, load Delta's built-in `report-landed` skill when offered and follow its format.
