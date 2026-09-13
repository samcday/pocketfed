# PocketFed development

## Keep work visible through pull requests

Use this workflow for PocketFed work and related changes in `samcday` repositories
and forks. The user should have a real opportunity to review work as it develops.

- Work on a focused `codex/` branch, using an isolated worktree when the shared
  checkout contains unrelated changes. Commit only the intended task's changes,
  staging individual hunks when files contain unrelated edits.
  Split unrelated work into separate PRs and link dependent PRs across repositories.
- Open a PR once the first coherent patch is reviewable; use a draft while work
  is incomplete. Do not wait for the whole implementation, hardware access, or
  all validation to be finished. Use public PRs for public repositories; do not
  change repository visibility or expose private work to satisfy this rule.
  Creating and updating these PRs in `samcday` repositories is standing permission;
  do not repeatedly ask the user to approve routine pushes or draft creation.
- Reuse the PR as work develops. Push coherent updates at meaningful milestones
  during long tasks and before handing work off or reporting it finished. Keep
  the title and description aligned with the current scope, explaining the
  problem, resulting behavior, validation performed, limitations and remaining
  work. Distinguish planned checks from completed checks.
- Give the user the PR link early and include it in handoffs and final reports.
  Keep unfinished work in draft. When ready for human review, mark it ready,
  inspect CI and automated review feedback, and address or explain outstanding
  findings. Do not require a particular review vendor.
- Do not push directly to the default branch, merge a PR, or enable auto-merge
  without explicit user authorization for that action. Permission to push a
  branch or open a PR is not permission to merge. Passing CI or an automated
  review is not human approval. Honor authorization already given for the
  specific action rather than asking again.
- Verify the PR's base repository owner and branch before publishing, and select
  the destination explicitly. In particular, a `samcday` fork can default to its
  external upstream in GitHub tooling. Prefer a PR against the `samcday` fork;
  a PR targeting any repository outside `samcday` requires explicit user
  authorization for that upstream destination. Owning the head fork does not
  authorize opening a PR against someone else's base repository.
- Publish source, configuration, documentation and concise validation evidence.
  Keep credentials, personal device data and sensitive raw logs out of commits,
  PR descriptions and attachments. Check the diff before pushing; do not sweep
  unrelated shared-checkout work or generated artifacts into the PR.

Keep local experiments moving alongside the PR. Public CI, COPR builds and
published images are not prerequisites for an ephemeral hardware trial. If
publication is unavailable, continue useful local work, preserve the branch and
report the pending PR synchronization instead of claiming it is published.
