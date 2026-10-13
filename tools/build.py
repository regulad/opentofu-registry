"""Build manifest versions that have no release yet, and publish each as a GitHub Release.

A version is built exactly once. Versions that are already released are only checked against
the manifest; a changed source or commit is refused instead of being rebuilt.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mirror  # noqa: E402

# Fixed member metadata keeps archives byte-identical for identical inputs.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def fetch_source(build, folder):
    """Check out exactly build.commit from build.source into folder."""
    folder.mkdir(parents=True)
    git = ['git', '-C', str(folder)]
    subprocess.run(git + ['init', '--quiet'], check=True)
    subprocess.run(git + ['fetch', '--quiet', '--depth', '1', build.source, build.commit], check=True)
    subprocess.run(git + ['checkout', '--quiet', '--detach', 'FETCH_HEAD'], check=True)
    head = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    if head != build.commit:
        raise RuntimeError(f'{build.source} checked out {head}, expected {build.commit}')


def go_build(build, source, platform, output):
    """Cross-compile one platform the way the upstream GoReleaser configuration does."""
    goos, goarch = platform.split('_')
    env = dict(os.environ, CGO_ENABLED='0', GOOS=goos, GOARCH=goarch, GOTOOLCHAIN='auto')
    if goarch == 'arm':
        env['GOARM'] = '6'  # GoReleaser's default
    binary = output / build.binary_name(goos)
    subprocess.run(['go', 'build', '-trimpath', '-ldflags', f'-s -w -X main.version={build.version}',
                    '-o', str(binary), '.'], cwd=source, env=env, check=True)
    return binary


def make_zip(members, path):
    """Write a deterministic zip of (name, bytes, mode) members."""
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data, mode in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 3  # Unix, so the mode below is honoured
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def build_version(build, platforms, workdir, dist):
    """Build every platform of one version into dist and record its hashes."""
    source = workdir / 'src'
    fetch_source(build, source)
    license_file = source / 'LICENSE'
    dist.mkdir(parents=True)
    recorded = {'address': build.address, 'version': build.version, 'source': build.source,
                'commit': build.commit, 'archives': {}}
    sums = []
    for platform in platforms:
        binary = go_build(build, source, platform, workdir / 'bin' / platform)
        members = [(binary.name, binary.read_bytes(), 0o755)]
        if license_file.is_file():
            members.append(('LICENSE', license_file.read_bytes(), 0o644))
        archive = dist / build.archive_name(platform)
        make_zip(members, archive)
        recorded['archives'][platform] = {
            'filename': archive.name, 'h1': mirror.h1_zip(archive), 'zh': mirror.zh_file(archive)}
        sums.append(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}')
    (dist / 'hashes.json').write_text(json.dumps(recorded, indent=2) + '\n', encoding='utf-8')
    (dist / 'SHA256SUMS').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    return recorded


def publish(build, dist):
    notes = f'Built from {build.source}/commit/{build.commit}.'
    if build.note:
        notes += f'\n\n{build.note}'
    subprocess.run(['gh', 'release', 'create', build.tag, '--title', f'{build.address} {build.version}',
                    '--notes', notes, *sorted(str(path) for path in dist.iterdir())], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('manifest')
    parser.add_argument('dist', help='output directory; one subdirectory per built release tag')
    parser.add_argument('--no-publish', action='store_true', help='build only; do not query or create releases')
    parser.add_argument('--only', action='append', default=[], help='build only these platforms (testing)')
    args = parser.parse_args(argv)
    platforms, builds = mirror.load_manifest(args.manifest)
    if args.only:
        unknown = set(args.only) - set(platforms)
        if unknown:
            raise mirror.ManifestError(f'--only names platforms outside the manifest: {sorted(unknown)}')
        platforms = [platform for platform in platforms if platform in args.only]
    for build in builds:
        if not args.no_publish:
            recorded = mirror.gh_recorded(build.tag)
            if recorded is not None:
                mirror.check_recorded(build, recorded)
                print(f'{build.tag}: already published, unchanged')
                continue
        dist = Path(args.dist) / build.tag
        with tempfile.TemporaryDirectory(prefix='mirror-build-') as workdir:
            build_version(build, platforms, Path(workdir), dist)
        if not args.no_publish:
            publish(build, dist)
            shutil.rmtree(dist)
        print(f'{build.tag}: built {len(platforms)} platform(s)')


if __name__ == '__main__':
    try:
        main()
    except (mirror.ManifestError, mirror.ImmutableError) as error:
        sys.exit(str(error))
