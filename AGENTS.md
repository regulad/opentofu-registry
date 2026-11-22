# Agent guide: `regulad/opentofu-registry`

A static OpenTofu provider network mirror on GitHub Pages; see `README.md`.

## Rules

- `providers.toml` is the only place builds are declared. Never edit, re-tag or delete a
  published release: published builds are immutable. Change a build by adding a new version.
- Mirrored versions must be valid semver that cannot collide with an upstream release.
- Usage docs must list `direct {}` before `network_mirror`. OpenTofu installs from the first
  method that has the selected version, and a mirror 404 stops it. `tofu providers lock`
  needs `-net-mirror` because it ignores the CLI configuration.
- `tools/mirror.py` must keep producing OpenTofu's `h1:` hash exactly; the CI lock-file
  vector check guards it. Keep both tools standard-library Python.
- Pages configuration and DNS live outside the repository (see `README.md`); changing them
  is an outward-facing action that needs Parker's approval.
- `README.md` and this file describe intent and current state only.
