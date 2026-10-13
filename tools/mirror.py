"""Shared helpers for the OpenTofu provider network mirror.

The mirror protocol is two JSON documents per provider (an index and one per version); see
https://opentofu.org/docs/internals/provider-network-mirror-protocol/. Archives live in this
repository's GitHub Releases, and each release's hashes.json records how it was built.
"""
import argparse
import base64
from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import zipfile

ADDRESS_RE = re.compile(r'(?P<host>[a-z0-9][a-z0-9.-]*)/(?P<namespace>[a-z0-9][a-z0-9-]*)/(?P<type>[a-z0-9][a-z0-9-]*)')
# Semantic versioning 2.0.0, without a leading "v".
VERSION_RE = re.compile(
    r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
    r'(-(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?'
    r'(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?')
PLATFORM_RE = re.compile(r'[a-z0-9]+_[a-z0-9]+')
COMMIT_RE = re.compile(r'[0-9a-f]{40}')
SOURCE_RE = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
MIRROR_URL = 'https://opentofu.regulad.xyz/'


class ManifestError(ValueError):
    """The manifest is malformed."""


class ImmutableError(RuntimeError):
    """A published build no longer matches its manifest entry."""


@dataclass(frozen=True)
class Build:
    address: str
    version: str
    source: str
    commit: str
    note: str = ''

    @property
    def host(self):
        return self.address.split('/')[0]

    @property
    def namespace(self):
        return self.address.split('/')[1]

    @property
    def type(self):
        return self.address.split('/')[2]

    @property
    def tag(self):
        """The GitHub Release tag in this repository that holds the build."""
        return f'{self.namespace}-{self.type}-v{self.version}'

    def archive_name(self, platform):
        return f'terraform-provider-{self.type}_{self.version}_{platform}.zip'

    def binary_name(self, goos):
        return f'terraform-provider-{self.type}_v{self.version}' + ('.exe' if goos == 'windows' else '')


def load_manifest(path):
    """Return (platforms, builds) from providers.toml, validating every field."""
    with open(path, 'rb') as stream:
        data = tomllib.load(stream)
    platforms = data.get('platforms')
    if not isinstance(platforms, list) or not platforms:
        raise ManifestError('platforms must be a non-empty list')
    for platform in platforms:
        if not isinstance(platform, str) or not PLATFORM_RE.fullmatch(platform):
            raise ManifestError(f'invalid platform {platform!r}; expected <os>_<arch>')
    if len(set(platforms)) != len(platforms):
        raise ManifestError('platforms contains duplicates')
    builds, tags = [], set()
    for provider in data.get('providers', []):
        address = provider.get('address', '')
        if not ADDRESS_RE.fullmatch(address):
            raise ManifestError(f'invalid provider address {address!r}; expected host/namespace/type')
        for entry in provider.get('versions', []):
            build = Build(address, entry.get('version', ''), entry.get('source', ''),
                          entry.get('commit', ''), entry.get('note', ''))
            if not VERSION_RE.fullmatch(build.version):
                raise ManifestError(f'{address}: invalid version {build.version!r}')
            if not SOURCE_RE.fullmatch(build.source):
                raise ManifestError(f'{address} {build.version}: source must be an https://github.com/<owner>/<repo> URL')
            if not COMMIT_RE.fullmatch(build.commit):
                raise ManifestError(f'{address} {build.version}: commit must be a full 40-character SHA')
            if build.tag in tags:
                raise ManifestError(f'{address} {build.version}: duplicate version')
            tags.add(build.tag)
            builds.append(build)
    if not builds:
        raise ManifestError('the manifest lists no provider versions')
    return platforms, builds


def h1_zip(path):
    """OpenTofu's h1: package hash, a port of Go's dirhash.HashZip with dirhash.Hash1."""
    summary = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if '\n' in name:
                raise ValueError('file names containing newlines are not supported')
            with archive.open(name) as member:
                digest = hashlib.sha256(member.read()).hexdigest()
            summary.update(f'{digest}  {name}\n'.encode())
    return 'h1:' + base64.b64encode(summary.digest()).decode('ascii')


def zh_file(path):
    """The zh: hash, which is the SHA-256 of the archive itself."""
    return 'zh:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_recorded(build, recorded):
    """Refuse a manifest entry that no longer describes its published release."""
    expected = {'address': build.address, 'version': build.version, 'source': build.source, 'commit': build.commit}
    changed = [key for key, value in expected.items() if recorded.get(key) != value]
    if changed:
        raise ImmutableError(
            f'{build.tag} was published with different {", ".join(changed)}; published builds are immutable, '
            'so add a new version (bump the build counter) instead of editing this one')


def release_url(repo, build, filename):
    return f'https://github.com/{repo}/releases/download/{build.tag}/{filename}'


def render_site(builds, recorded_by_tag, repo, out):
    """Write the mirror's JSON documents and a landing page into out."""
    out = Path(out)
    by_address = {}
    for build in builds:
        recorded = recorded_by_tag.get(build.tag)
        if recorded is None:
            raise ImmutableError(f'{build.tag} has no published release; run the build first')
        check_recorded(build, recorded)
        by_address.setdefault(build.address, []).append((build, recorded))
    for address, entries in by_address.items():
        folder = out.joinpath(*address.split('/'))
        folder.mkdir(parents=True, exist_ok=True)
        index = {'versions': {build.version: {} for build, _ in entries}}
        (folder / 'index.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')
        for build, recorded in entries:
            archives = {
                platform: {'url': release_url(repo, build, info['filename']), 'hashes': [info['h1']]}
                for platform, info in sorted(recorded['archives'].items())
            }
            (folder / f'{build.version}.json').write_text(
                json.dumps({'archives': archives}, indent=2) + '\n', encoding='utf-8')
    (out / 'index.html').write_text(landing_page(builds, repo), encoding='utf-8')


def landing_page(builds, repo):
    addresses = sorted({build.address for build in builds})
    rows = '\n'.join(
        f'<li><code>{html.escape(build.address)}</code> {html.escape(build.version)}'
        f'{" — " + html.escape(build.note) if build.note else ""}</li>'
        for build in builds)
    includes = ', '.join(f'"{html.escape(address)}"' for address in addresses)
    return f'''<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>OpenTofu provider mirror</title>
<h1>OpenTofu provider mirror</h1>
<p>A provider network mirror for builds that are not yet released upstream.
Source: <a href="https://github.com/{html.escape(repo)}">{html.escape(repo)}</a>.</p>
<p>List <code>direct</code> first: OpenTofu installs from the first method that has the
selected version, so official releases come from the registry and these builds from here.</p>
<pre>provider_installation {{
  direct {{}}
  network_mirror {{
    url     = "{MIRROR_URL}"
    include = [{includes}]
  }}
}}</pre>
<p>To lock other platforms: <code>tofu providers lock -net-mirror={MIRROR_URL} -platform=&lt;os&gt;_&lt;arch&gt;</code></p>
<h2>Builds</h2>
<ul>
{rows}
</ul>
'''


def gh_recorded(tag):
    """Download a release's hashes.json, or return None when the release does not exist."""
    view = subprocess.run(['gh', 'release', 'view', tag, '--json', 'tagName'], capture_output=True, text=True)
    if view.returncode != 0:
        return None
    payload = subprocess.check_output(['gh', 'release', 'download', tag, '--pattern', 'hashes.json', '--output', '-'])
    return json.loads(payload)


def check_lock_vector(archive, fixture):
    """Assert an archive's h1:/zh: hashes appear in a lock-file hash list."""
    known = {line.strip() for line in Path(fixture).read_text(encoding='utf-8').splitlines() if line.strip()}
    for value in (h1_zip(archive), zh_file(archive)):
        if value not in known:
            raise SystemExit(f'{value} is not among the hashes in {fixture}')
        print(f'ok {value}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    site = commands.add_parser('site', help='render the mirror from published releases')
    site.add_argument('manifest')
    site.add_argument('out')
    check = commands.add_parser('check-lock-vector', help='verify the hash functions against a lock file')
    check.add_argument('archive')
    check.add_argument('fixture')
    args = parser.parse_args(argv)
    if args.command == 'site':
        _, builds = load_manifest(args.manifest)
        repo = os.environ['GITHUB_REPOSITORY']
        recorded = {build.tag: gh_recorded(build.tag) for build in builds}
        render_site(builds, {tag: value for tag, value in recorded.items() if value is not None}, repo, args.out)
    else:
        check_lock_vector(args.archive, args.fixture)


if __name__ == '__main__':
    try:
        main()
    except (ManifestError, ImmutableError) as error:
        sys.exit(str(error))
