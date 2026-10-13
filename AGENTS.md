# Agent guide: `regulad/opentofu-registry`

A static OpenTofu provider network mirror on GitHub Pages; see `README.md`.

## Commits

- Every commit created or rewritten by an AI agent carries that agent's own
  `Co-Authored-By` trailer; Parker Wahle remains author and committer.
- Keep commit signing enabled; never bypass it.
- Never add a `Signed-off-by` trailer with Parker's identity unless he says so for those commits.
- Commit only when Parker asks. Conventional-commit messages.

## Rules

- `providers.toml` is the only place builds are declared. Never edit, re-tag or delete a
  published release: published builds are immutable. Change a build by adding a new version.
- Mirrored versions must be valid semver that cannot collide with an upstream release.
- Pin every action by commit SHA with a version comment.
- `tools/mirror.py` must keep producing OpenTofu's `h1:` hash exactly; the CI lock-file
  vector check guards it. Keep both tools standard-library Python.
- Pages configuration and DNS live outside the repository (see `README.md`); changing them
  is an outward-facing action that needs Parker's approval.
- `README.md` and this file describe intent and current state only.
