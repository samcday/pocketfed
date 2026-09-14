# Upstream and Fedora follow-up

This public downstream report preserves the patch, reproducer and results
while upstream review and distribution adoption remain open.

1. Recheck GTK issues and merge requests for a duplicate, then link or file
   the focused bug report through the GNOME GTK tracker.
2. Have the human submitter review and understand the candidate and harness;
   confirm licensing for the standalone harness, build/test current main,
   and use a GTK merge request for the patch.
3. Record the upstream issue/MR and accepted commit here and in the PocketFed
   tracking issue. Complete upstream CI and respond to review personally.
4. Track the Fedora GTK build that contains the accepted correction. Validate
   that build against the preedit matrix and a real Phosh/Stevia session.
5. Retire the local hotfix requirement, COPR package selection and device RPM
   override once the replacement is verified, so an old patched package does
   not shadow newer Fedora fixes.

## GTK contribution policy checked September 8, 2026

The official
[CONTRIBUTING.md at `539d28f33b6d285a784c220e6c53ec499d75c078`](https://gitlab.gnome.org/GNOME/gtk/-/blob/539d28f33b6d285a784c220e6c53ec499d75c078/CONTRIBUTING.md#ai-contribution-policy)
permits LLM/GenAI-assisted contributions under stated conditions: a human
must verify and understand the work, keep changes narrow, and disclose AI use
in issues and merge requests. It prohibits feeding review feedback to an LLM
and does not accept generated review comments/feedback. Do not add AI-company
credit trailers to GTK commit messages. GTK also requests patches through
merge requests, rather than patch attachments on issues.

That is GTK's project-specific policy; it does not establish policy for
other GNOME projects. This report and tracking work do not represent a human
submitter's sign-off or claim they have personally reviewed every line.

Policy was fetched from GNOME's public GitLab API at the fixed revision above;
SHA-256 of the full UTF-8 file was
`019bedd9ac665970dd6da333925f5399af3ac1ebf103681560f2aab2905eeea0`.
The API's main revision, relevant file history, current callback, and issue/MR
searches were read on September 8. The candidate patch passed
`patch --dry-run --fuzz=0 -p1` against that callback's source file. No current
GTK build, full suite or new phone trial was run for this publication check.
