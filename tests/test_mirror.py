import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import build as builder  # noqa: E402
import mirror  # noqa: E402

COMMIT = '5412a2722eeb6f26ee25ada15e644370fe424c9c'
SOURCE = 'https://github.com/regulad/terraform-provider-proxmox'
MANIFEST = f'''
platforms = ["linux_amd64", "windows_amd64"]

[[providers]]
address = "registry.opentofu.org/bpg/proxmox"

[[providers.versions]]
version = "0.117.0-pr3167.1"
source = "{SOURCE}"
commit = "{COMMIT}"
note = "pending upstream"
'''


def write(folder, name, text):
    path = Path(folder) / name
    path.write_text(text, encoding='utf-8')
    return path


def recorded_for(build, platforms):
    return {'address': build.address, 'version': build.version, 'source': build.source, 'commit': build.commit,
            'archives': {p: {'filename': build.archive_name(p), 'h1': f'h1:{p}', 'zh': f'zh:{p}'} for p in platforms}}


class HashTests(unittest.TestCase):
    def test_h1_matches_dirhash_hash1(self):
        files = {'b.txt': b'second\n', 'a.txt': b'first\n'}
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'p.zip'
            builder.make_zip([(name, data, 0o644) for name, data in files.items()], archive)
            summary = ''.join(f'{hashlib.sha256(files[name]).hexdigest()}  {name}\n' for name in sorted(files))
            expected = 'h1:' + base64.b64encode(hashlib.sha256(summary.encode()).digest()).decode()
            self.assertEqual(mirror.h1_zip(archive), expected)
            self.assertEqual(mirror.zh_file(archive), 'zh:' + hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_zip_is_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / '1.zip', Path(folder) / '2.zip'
            for path in (first, second):
                builder.make_zip([('terraform-provider-x_v1.0.0', b'binary', 0o755)], path)
            self.assertEqual(first.read_bytes(), second.read_bytes())


class ManifestTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as folder:
            return mirror.load_manifest(write(folder, 'providers.toml', text))

    def test_valid_manifest(self):
        platforms, builds = self.load(MANIFEST)
        self.assertEqual(platforms, ['linux_amd64', 'windows_amd64'])
        (build,) = builds
        self.assertEqual(build.tag, 'bpg-proxmox-v0.117.0-pr3167.1')
        self.assertEqual(build.archive_name('linux_amd64'), 'terraform-provider-proxmox_0.117.0-pr3167.1_linux_amd64.zip')
        self.assertEqual(build.binary_name('windows'), 'terraform-provider-proxmox_v0.117.0-pr3167.1.exe')
        self.assertEqual(build.binary_name('linux'), 'terraform-provider-proxmox_v0.117.0-pr3167.1')

    def test_rejects_invalid_entries(self):
        cases = {
            'short commit': MANIFEST.replace(COMMIT, COMMIT[:12]),
            'leading v': MANIFEST.replace('"0.117.0-pr3167.1"', '"v0.117.0-pr3167.1"'),
            'non-GitHub source': MANIFEST.replace(SOURCE, 'https://example.com/fork'),
            'bad address': MANIFEST.replace('registry.opentofu.org/bpg/proxmox', 'bpg/proxmox'),
            'bad platform': MANIFEST.replace('"windows_amd64"', '"windows"'),
            'duplicate platform': MANIFEST.replace('"windows_amd64"', '"linux_amd64"'),
            'duplicate version': MANIFEST + MANIFEST[MANIFEST.index('[[providers.versions]]'):],
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(mirror.ManifestError):
                self.load(text)


class SiteTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as folder:
            self.platforms, (self.build,) = mirror.load_manifest(write(folder, 'providers.toml', MANIFEST))

    def test_renders_mirror_documents(self):
        with tempfile.TemporaryDirectory() as out:
            mirror.render_site([self.build], {self.build.tag: recorded_for(self.build, self.platforms)},
                               'regulad/opentofu-registry', out)
            root = Path(out) / 'registry.opentofu.org' / 'bpg' / 'proxmox'
            self.assertEqual(json.loads((root / 'index.json').read_text()), {'versions': {'0.117.0-pr3167.1': {}}})
            archives = json.loads((root / '0.117.0-pr3167.1.json').read_text())['archives']
            self.assertEqual(sorted(archives), self.platforms)
            self.assertEqual(archives['linux_amd64'], {
                'url': 'https://github.com/regulad/opentofu-registry/releases/download/bpg-proxmox-v0.117.0-pr3167.1/'
                       'terraform-provider-proxmox_0.117.0-pr3167.1_linux_amd64.zip',
                'hashes': ['h1:linux_amd64'],
            })
            self.assertIn('network_mirror', (Path(out) / 'index.html').read_text())

    def test_refuses_changed_commit(self):
        recorded = recorded_for(self.build, self.platforms)
        recorded['commit'] = '0' * 40
        with tempfile.TemporaryDirectory() as out, self.assertRaisesRegex(mirror.ImmutableError, 'bump the build counter'):
            mirror.render_site([self.build], {self.build.tag: recorded}, 'regulad/opentofu-registry', out)

    def test_refuses_unpublished_version(self):
        with tempfile.TemporaryDirectory() as out, self.assertRaisesRegex(mirror.ImmutableError, 'no published release'):
            mirror.render_site([self.build], {}, 'regulad/opentofu-registry', out)


if __name__ == '__main__':
    unittest.main()
