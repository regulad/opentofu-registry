# OpenTofu provider mirror

An [OpenTofu provider network mirror](https://opentofu.org/docs/internals/provider-network-mirror-protocol/)
at **https://opentofu.regulad.xyz/** for provider builds that are not released upstream yet,
such as a fork carrying an open pull request, and for providers of our own that are on no
registry. The mirror serves them under the provider's normal address (e.g. `bpg/proxmox`),
so switching to the official release later needs no state migration.

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
  version = "= 0.117.0-pr3167.pr3170.1"
}
```

A provider on no registry, our own or one never published upstream such as `himanoa/ga4`,
has the mirror as its only source; leave it out of `direct`:

```hcl
provider_installation {
  direct {
    exclude = ["registry.opentofu.org/regulad/onesignal"]
  }
  network_mirror {
    url     = "https://opentofu.regulad.xyz/"
    include = ["registry.opentofu.org/regulad/onesignal"]
  }
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
| `bpg/proxmox` | `0.117.0-pr3167.pr3170.1` | `regulad/terraform-provider-proxmox` @ `d1f1041a` (`combo/3167-3170`) | #3167 plus string-typed container `cpus`, pending [bpg/terraform-provider-proxmox#3170](https://github.com/bpg/terraform-provider-proxmox/pull/3170) |
| `bpg/proxmox` | `0.118.0-pr3204.pr3207.pr3209.1` | `regulad/terraform-provider-proxmox` @ `f21dae85` (`combo/3204-3207-3209`) | Ceph on upstream `main` after 0.117.0: the pool import fix and `proxmox_storage_rbd` ([#3204](https://github.com/bpg/terraform-provider-proxmox/pull/3204)), `proxmox_ceph_mds` ([#3207](https://github.com/bpg/terraform-provider-proxmox/pull/3207)), `proxmox_ceph_fs` and `proxmox_storage_cephfs` ([#3209](https://github.com/bpg/terraform-provider-proxmox/pull/3209)) |
| `integrations/github` | `6.14.0-pr2366.1` | `regulad/terraform-provider-github` @ `ece9a53d` (`rebase/2366`) | `github_user_ssh_signing_key`, pending [integrations/terraform-provider-github#2366](https://github.com/integrations/terraform-provider-github/pull/2366), applied onto upstream `main` |
| `integrations/github` | `6.14.0-pr2366.pr3747.1` | `regulad/terraform-provider-github` @ `edf00a9e` (`combo/2366-3747`) | #2366 plus import for `github_user_gpg_key`, pending [integrations/terraform-provider-github#3747](https://github.com/integrations/terraform-provider-github/pull/3747) |
| `regulad/onesignal` | `0.1.0` | `regulad/terraform-provider-onesignal` @ `1266efa8` (`v0.1.0`) | Our own provider for OneSignal, on no registry |
| `himanoa/ga4` | `0.1.0-remaining.2` | `regulad/terraform-provider-ga4` @ `3bf03534` (`remaining`) | The rest of the Google Analytics Admin API's v1beta on himanoa/terraform-provider-ga4, which has no release and is on no registry, with imported properties recording `acknowledge_user_data_collection` as false |

`providers.toml` is the source of truth. Each version names its source repository, an
exact commit and a note. The platform list mirrors upstream's release matrix.

## How it works

`.github/workflows/publish.yml` runs on every push to `master` and on manual dispatch. A
pull request to `master` runs **test** and **build**, both checks it must pass to merge; its
build creates no release:

1. **test:** unit tests, then checks the `h1:`/`zh:` hash code against real
   `oracle/oci` 9.9.0 lock-file hashes (`tests/fixtures/`).
2. **build** (on a pull request) or **release** (otherwise): `tools/build.py` checks every
   released version against its manifest entry, then builds each one that has no release yet:
   - fetches exactly the pinned commit;
   - cross-compiles every platform the way upstream's GoReleaser does
     (`CGO_ENABLED=0`, `-trimpath`, `-s -w -X main.version=…`);
   - zips the binary with the source's `LICENSE` using fixed metadata;
   - except on a pull request (`--dry-run`), publishes a GitHub Release tagged
     `<namespace>-<type>-v<version>`, holding the zips, `SHA256SUMS` and `hashes.json`.
3. **site:** `tools/mirror.py site` renders `/<host>/<namespace>/<type>/index.json` and
   `/<version>.json` from each release's `hashes.json`. Archive URLs point at the release
   assets.
4. **deploy:** the rendered site is uploaded and deployed with GitHub Pages' Actions flow.

## Adding or changing a build

Add a `[[providers.versions]]` entry to `providers.toml` and push. **Published builds are
immutable:** a release is built once and never rebuilt, so existing lock files stay valid.
Editing an existing entry's source or commit fails the workflow, on the pull request too. Add a new version with the
next build counter instead (`0.117.0-pr3167.2`). Removing an entry stops the mirror listing
it; its release stays, so old lock files can still download it by URL.

Version strings must be valid semver and must never collide with an upstream release. Use
the next upstream version a change would land in, plus `-pr<number>.<build>`. A provider of
our own has no upstream: its versions are its own release tags (`0.1.0`). A build that
combines several pull requests names each one (`0.117.0-pr3167.pr3170.1`) and is built from
a fork branch that merges their branches. A change not yet offered upstream has no pull
request number, so it names its fork branch instead (`0.1.0-remaining.1`), with the next
upstream version as the base; for an upstream with no release yet, that is `0.1.0`.

## Local checks

```sh
python -m unittest discover -s tests -v
python tools/build.py providers.toml dist --no-publish --only linux_amd64   # needs Go
python tools/build.py providers.toml dist --dry-run --only linux_amd64      # also needs gh
```

## One-time setup

1. **Pages:** set the build type to GitHub Actions, the custom domain to
   `opentofu.regulad.xyz`, and enforce HTTPS (`gh api repos/regulad/opentofu-registry/pages`).
   The Settings app in `.github/settings.yml` does not manage Pages.
2. **DNS:** `opentofu.regulad.xyz` is a `CNAME` to `regulad.github.io`, and the `regulad.xyz`
   domain is verified for GitHub Pages so the name can't be taken over.

## License

The tooling is licensed under the [GNU AGPLv3](LICENSE.md). The mirrored provider binaries
keep their own licenses (MPL-2.0 for `bpg/proxmox` and `regulad/onesignal`, MIT for `integrations/github`); each archive includes the source's
`LICENSE`, and every release names the exact source commit.
