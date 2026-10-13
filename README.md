# OpenTofu provider mirror

An [OpenTofu provider network mirror](https://opentofu.org/docs/internals/provider-network-mirror-protocol/)
at **https://opentofu.regulad.xyz/** for provider builds that are not released upstream yet,
such as a fork carrying an open pull request. The mirror serves them under the provider's
normal address (e.g. `bpg/proxmox`), so switching to the official release later needs no
state migration.

## Using it

Add the mirror to the OpenTofu CLI configuration, limited to the providers it carries, and
list `direct` **first**:

```hcl
provider_installation {
  direct {}
  network_mirror {
    url     = "https://opentofu.regulad.xyz/"
    include = ["registry.opentofu.org/bpg/proxmox"]
  }
}
```

OpenTofu picks the newest version that matches the constraint, from all matching methods.
It then installs that version from the first method, in configuration order, that has it.
A mirror listed first returns 404 for official releases and stops the install. With
`direct` first, official releases come from the registry, and versions the registry lacks
fall through to the mirror. Pin a mirrored build exactly:

```hcl
proxmox = {
  source  = "bpg/proxmox"
  version = "= 0.117.0-pr3167.1"
}
```

Lock-file hashes (`h1:`) are checked as usual. The mirror protocol relies on HTTPS and those
hashes; there are no GPG signatures. `tofu providers lock` ignores the CLI configuration and
asks the origin registry, so point it at the mirror to record every platform:

```sh
tofu providers lock -net-mirror=https://opentofu.regulad.xyz/ -platform=linux_amd64 -platform=windows_amd64
```

## Builds

| Provider | Version | Source | Why |
|---|---|---|---|
| `bpg/proxmox` | `0.117.0-pr3167.1` | `regulad/terraform-provider-proxmox` @ `5412a272` | `proxmox_custom_cpu_model`, pending [bpg/terraform-provider-proxmox#3167](https://github.com/bpg/terraform-provider-proxmox/pull/3167) |

`providers.toml` is the source of truth. Each version names its source repository, an
exact commit and a note. The platform list mirrors upstream's release matrix.

## How it works

`.github/workflows/publish.yml` runs on every push to `master` and on manual dispatch:

1. **test:** unit tests, then checks the `h1:`/`zh:` hash code against real
   `oracle/oci` 9.9.0 lock-file hashes (`tests/fixtures/`).
2. **build:** `tools/build.py` builds each manifest version that has no release yet:
   - fetches exactly the pinned commit;
   - cross-compiles every platform the way upstream's GoReleaser does
     (`CGO_ENABLED=0`, `-trimpath`, `-s -w -X main.version=…`);
   - zips the binary with the source's `LICENSE` using fixed metadata;
   - publishes a GitHub Release tagged `<namespace>-<type>-v<version>`, holding the
     zips, `SHA256SUMS` and `hashes.json`.
3. **site:** `tools/mirror.py site` renders `/<host>/<namespace>/<type>/index.json` and
   `/<version>.json` from each release's `hashes.json`. Archive URLs point at the release
   assets.
4. **deploy:** the rendered site is uploaded and deployed with GitHub Pages' Actions flow.

## Adding or changing a build

Add a `[[providers.versions]]` entry to `providers.toml` and push. **Published builds are
immutable:** a release is built once and never rebuilt, so existing lock files stay valid.
Editing an existing entry's source or commit fails the workflow. Add a new version with the
next build counter instead (`0.117.0-pr3167.2`). Removing an entry stops the mirror listing
it; its release stays, so old lock files can still download it by URL.

Version strings must be valid semver and must never collide with an upstream release. Use
the next upstream version a change would land in, plus `-pr<number>.<build>`.

## Local checks

```sh
python -m unittest discover -s tests -v
python tools/build.py providers.toml dist --no-publish --only linux_amd64   # needs Go
```

## One-time setup

1. **Pages:** set the build type to GitHub Actions, the custom domain to
   `opentofu.regulad.xyz`, and enforce HTTPS (`gh api repos/regulad/opentofu-registry/pages`).
   The Settings app in `.github/settings.yml` does not manage Pages.
2. **DNS:** `opentofu.regulad.xyz` is a `CNAME` to `regulad.github.io`, and the `regulad.xyz`
   domain is verified for GitHub Pages so the name can't be taken over.

## License

The tooling is licensed under the [GNU AGPLv3](LICENSE.md). The mirrored provider binaries
keep their own licenses (MPL-2.0 for `bpg/proxmox`); each archive includes the source's
`LICENSE`, and every release names the exact source commit.
