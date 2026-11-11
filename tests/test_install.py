# -*- coding: utf-8 -*-
import hashlib
import io
import os
import platform
import shutil
import tarfile
from pathlib import Path

import pytest

from django_sass_finder import install as installer
from django_sass_finder._checksums import CHECKSUMS


@pytest.mark.parametrize('system, machine, tag', [
    ('Darwin', 'arm64', 'macos-arm64'),
    ('Darwin', 'x86_64', 'macos-x64'),
    ('Linux', 'x86_64', 'linux-x64'),
    ('Linux', 'aarch64', 'linux-arm64'),
    ('Linux', 'armv7l', 'linux-arm'),
    ('Windows', 'AMD64', 'windows-x64'),
    ('Windows', 'ARM64', 'windows-arm64'),
])
def test_platform_tag(monkeypatch, system, machine, tag):
    monkeypatch.setattr(platform, 'system', lambda: system)
    monkeypatch.setattr(platform, 'machine', lambda: machine)
    monkeypatch.setattr(installer, '_is_musl', lambda: False)
    assert installer.platform_tag() == tag


def test_platform_tag_musl(monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(installer, '_is_musl', lambda: True)
    assert installer.platform_tag() == 'linux-x64-musl'


@pytest.mark.parametrize('system, machine', [('FreeBSD', 'x86_64'), ('Linux', 'sparc64')])
def test_platform_tag_unsupported(monkeypatch, system, machine):
    monkeypatch.setattr(platform, 'system', lambda: system)
    monkeypatch.setattr(platform, 'machine', lambda: machine)
    with pytest.raises(installer.InstallError):
        installer.platform_tag()


def test_archive_name():
    assert installer.archive_name('1.2.3', 'linux-x64') == 'dart-sass-1.2.3-linux-x64.tar.gz'
    assert installer.archive_name('1.2.3', 'windows-x64') == 'dart-sass-1.2.3-windows-x64.zip'


def test_shipped_checksums_cover_the_default_version():
    names = {name for name in CHECKSUMS if f'-{installer.DEFAULT_DART_SASS_VERSION}-' in name}
    assert installer.archive_name(installer.DEFAULT_DART_SASS_VERSION, 'linux-x64') in names
    assert installer.archive_name(installer.DEFAULT_DART_SASS_VERSION, 'macos-arm64') in names
    assert len(names) == len(CHECKSUMS)     # nothing for other versions left behind


def test_default_version_matches_this_projects_pyproject():
    """This repository's own pyproject.toml pins the version CI installs."""
    root = Path(__file__).resolve().parent.parent
    assert installer.resolve_version(start=root) == installer.DEFAULT_DART_SASS_VERSION


class TestResolveVersion:
    @pytest.fixture(autouse=True)
    def clean_env(self, monkeypatch):
        monkeypatch.delenv('DART_SASS_VERSION', raising=False)

    def test_default_without_pyproject(self, tmp_path):
        assert installer.resolve_version(start=tmp_path) == installer.DEFAULT_DART_SASS_VERSION

    def test_from_pyproject_searching_upwards(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[tool.django-sass-finder]\ndart-sass-version = "1.2.3"\n')
        sub = tmp_path / 'a' / 'b'
        sub.mkdir(parents=True)
        assert installer.resolve_version(start=sub) == '1.2.3'

    def test_pyproject_without_our_table(self, tmp_path):
        (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n')
        assert installer.resolve_version(start=tmp_path) == installer.DEFAULT_DART_SASS_VERSION

    def test_precedence(self, tmp_path, monkeypatch):
        (tmp_path / 'pyproject.toml').write_text('[tool.django-sass-finder]\ndart-sass-version = "1.2.3"\n')
        monkeypatch.setenv('DART_SASS_VERSION', '2.0.0')
        assert installer.resolve_version(start=tmp_path) == '2.0.0'
        assert installer.resolve_version('3.0.0', start=tmp_path) == '3.0.0'


class TestInstall:
    VERSION = '9.9.9'

    @pytest.fixture
    def fake_release(self, tmp_path, monkeypatch):
        """A tiny release archive in place of the download; returns its sha256."""
        monkeypatch.setattr(installer, 'platform_tag', lambda: 'linux-x64')
        monkeypatch.setattr(platform, 'system', lambda: 'Linux')
        archive = tmp_path / 'release.tar.gz'
        with tarfile.open(archive, 'w:gz') as tf:
            for name, content in {'dart-sass/sass': b'#!/bin/sh\necho 9.9.9\n',
                                  'dart-sass/src/dart': b'binary'}.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o644
                tf.addfile(info, io.BytesIO(content))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        downloads = []

        def fake_download(url, destination):
            downloads.append(url)
            shutil.copy(archive, destination)
            return digest

        monkeypatch.setattr(installer, '_download', fake_download)
        monkeypatch.setattr(installer, '_expected_sha256', lambda version, filename: digest)
        return type('Release', (), {'digest': digest, 'downloads': downloads})

    def run(self, tmp_path, **kwargs):
        return installer.install(self.VERSION, prefix=tmp_path / 'env', bin_dir=tmp_path / 'env' / 'bin', **kwargs)

    def test_installs_and_links_executable(self, tmp_path, fake_release):
        exe = self.run(tmp_path)
        assert exe == tmp_path / 'env' / 'bin' / 'sass'
        assert exe.is_symlink()
        launcher = tmp_path / 'env' / 'dart-sass' / self.VERSION / 'dart-sass' / 'sass'
        assert exe.resolve() == launcher.resolve()
        assert launcher.stat().st_mode & 0o111      # made executable
        assert (launcher.parent / 'src' / 'dart').stat().st_mode & 0o111     # and so is the runtime
        assert fake_release.downloads == [
            f'{installer.RELEASES_URL}/{self.VERSION}/dart-sass-{self.VERSION}-linux-x64.tar.gz']

    def test_does_not_download_twice(self, tmp_path, fake_release):
        self.run(tmp_path)
        self.run(tmp_path)
        assert len(fake_release.downloads) == 1
        self.run(tmp_path, force=True)
        assert len(fake_release.downloads) == 2

    def test_rejects_checksum_mismatch(self, tmp_path, fake_release, monkeypatch):
        monkeypatch.setattr(installer, '_expected_sha256', lambda version, filename: '0' * 64)
        with pytest.raises(installer.InstallError, match='Checksum mismatch'):
            self.run(tmp_path)
        assert not (tmp_path / 'env' / 'bin' / 'sass').exists()
        assert not (tmp_path / 'env' / 'dart-sass' / self.VERSION).exists()

    def test_no_verify_skips_the_check(self, tmp_path, fake_release, monkeypatch):
        def explode(version, filename):
            raise AssertionError('should not be asked')
        monkeypatch.setattr(installer, '_expected_sha256', explode)
        assert self.run(tmp_path, verify=False).exists()

    def test_refuses_outside_a_virtualenv(self, monkeypatch):
        monkeypatch.setattr(installer.sys, 'prefix', installer.sys.base_prefix)
        with pytest.raises(installer.InstallError, match='virtualenv'):
            installer.install(self.VERSION)

    def test_main_reports_errors(self, capsys, monkeypatch):
        monkeypatch.setattr(installer.sys, 'prefix', installer.sys.base_prefix)
        assert installer.main(['--version', self.VERSION]) == 1
        assert 'virtualenv' in capsys.readouterr().err

    def test_rejects_a_release_that_reports_another_version(self, tmp_path, fake_release):
        with pytest.raises(installer.InstallError, match='did not report version'):
            installer.install('8.8.8', prefix=tmp_path / 'env', bin_dir=tmp_path / 'env' / 'bin')
        assert not (tmp_path / 'env' / 'bin' / 'sass').exists()
        assert not (tmp_path / 'env' / 'dart-sass' / '8.8.8').exists()

    def test_force_keeps_the_old_install_if_the_new_one_is_bad(self, tmp_path, fake_release, monkeypatch):
        exe = self.run(tmp_path)
        launcher = exe.resolve()

        def broken(release, version):
            raise installer.InstallError('broken')
        monkeypatch.setattr(installer, '_verify', broken)
        with pytest.raises(installer.InstallError, match='broken'):
            self.run(tmp_path, force=True)
        assert launcher.is_file() and exe.exists()

    def test_force_restores_the_old_install_if_the_move_fails(self, tmp_path, fake_release, monkeypatch):
        exe = self.run(tmp_path)
        launcher = exe.resolve()
        real_rename = Path.rename

        def failing_rename(self, target):
            if self.name == 'unpacked':
                raise OSError('disk full')
            return real_rename(self, target)
        monkeypatch.setattr(Path, 'rename', failing_rename)
        with pytest.raises(OSError, match='disk full'):
            self.run(tmp_path, force=True)
        assert launcher.is_file()
        assert not launcher.parent.parent.with_name(self.VERSION + '.old').exists()

    def test_refuses_to_extract_without_a_tar_filter(self, tmp_path, fake_release, monkeypatch):
        monkeypatch.delattr(tarfile, 'data_filter')
        with pytest.raises(installer.InstallError, match='3.11.4'):
            self.run(tmp_path)
        assert not (tmp_path / 'env' / 'dart-sass' / self.VERSION).exists()
