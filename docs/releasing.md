# Releasing, and the settings that are not in this repository

## Cutting a release

1. Bump the version in `plugin/.claude-plugin/plugin.json`,
   `.claude-plugin/marketplace.json` and the `SCRIBE_VERSION` default in
   `docker-compose.yml`. All three must match the tag — CI checks the first
   two, the release workflow checks all three, and a compose file pointing at
   an unpublished tag gives new users `manifest unknown` as a first
   impression.
2. Push to `main` and let CI go green.
3. `gh release create vX.Y.Z --target main --title ... --notes ...`

Tagging triggers `.github/workflows/release.yml`, which builds amd64 and arm64,
pushes to ghcr.io with an SBOM and provenance, smoke-tests the published image
by digest, and only then attests it.

**Write the notes yourself.** `.github/release.yml` categorises what changed;
the paragraph at the top explains *why* it changed, which is the part anyone
actually reads. Say what broke, what a user has to do, and what was verified
rather than assumed.

If a release fixes a vulnerability, publish a GitHub advisory alongside it.

## After a dependency bump

Regenerating `server/requirements.lock` is the step that is easy to forget and
invisible when forgotten — the image installs the lock, so a bumped range moves
while the shipped version stays put. Two tests guard it: one compares every
`>=` floor against the locked version, one requires the lock header to name the
same Python as the `FROM` line. Trust them and run the command in the lock's
header.

## Repository settings (maintainer, not code)

These live in GitHub's UI and cannot be changed by editing files. Current state
checked with `gh api repos/OWNER/REPO`:

- [x] Secret scanning — enabled
- [x] Push protection — enabled
- [ ] **Private vulnerability reporting** — not enabled. `SECURITY.md` points
      reporters at the advisory form, so this one matters: Settings → Security
      → enable "Private vulnerability reporting"
- [ ] **Description** — still says "Send documents from Claude…", which is no
      longer accurate now that Codex and ChatGPT desktop are supported.
      Suggested: *Think with AI. Review with a pen. Send AI-generated work to a
      Kindle Scribe, annotate it by hand, and continue in any supported MCP
      client.*
- [ ] **Topics** — add `self-hosted`, `codex`, `chatgpt`, `knowledge-work`
      alongside the existing ones
- [ ] **Social preview** — 1280×640, under 1 MB: the tagline, the four-step
      loop, one annotated page. Not an architecture diagram
- [ ] **Ruleset for `main`** — block force pushes, block deletion, require CI
      to pass. Requiring pull requests is deliberately *not* recommended while
      this is a one-person project: it would add a review step with no reviewer

Dependabot alerts and security updates follow from `.github/dependabot.yml`,
which is already in the repository.
