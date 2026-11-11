"""
Install the Dart Sass compiler into the current virtualenv.

    python -m django_sass_finder.install [--version VERSION]

The official release archive for the running platform is downloaded from
https://github.com/sass/dart-sass/releases, verified against its SHA-256 digest, unpacked
into ``<prefix>/dart-sass/<version>`` and linked as ``sass`` into the environment's scripts
directory, so that it is on ``PATH`` whenever the virtualenv is active.

The version to install is, in order of precedence:

1. ``--version`` on the command line
2. the ``DART_SASS_VERSION`` environment variable
3. ``dart-sass-version`` in the ``[tool.django-sass-finder]`` table of the nearest
   ``pyproject.toml`` (searching upwards from the current directory)
4. ``DEFAULT_DART_SASS_VERSION``
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, Sequence

from ._checksums import CHECKSUMS

__all__ = (
    'DEFAULT_DART_SASS_VERSION',
    'InstallError',
    'archive_name',
    'install',
    'main',
    'resolve_version',
)

DEFAULT_DART_SASS_VERSION = '1.108.1'
RELEASES_URL = 'https://github.com/sass/dart-sass/releases/download'
API_URL = 'https://api.github.com/repos/sass/dart-sass/releases/tags'
PYPROJECT_TABLE = 'django-sass-finder'
TIMEOUT = 60


class InstallError(Exception):
    pass


def _is_musl() -> bool:
    return platform.system() == 'Linux' and any(Path('/lib').glob('ld-musl-*'))


def platform_tag() -> str:
    """The ``{os}-{arch}[-musl]`` part of the release archive name for this platform."""
    system = {'Darwin': 'macos', 'Linux': 'linux', 'Windows': 'windows'}.get(platform.system())
    if system is None:
        raise InstallError(f'No Dart Sass release for platform {platform.system()!r}')
    machine = platform.machine().lower()
    if machine in ('x86_64', 'amd64'):
        arch = 'x64'
    elif machine in ('arm64', 'aarch64'):
        arch = 'arm64'
    elif machine.startswith('arm'):
        arch = 'arm'
    elif machine == 'riscv64':
        arch = 'riscv64'
    else:
        raise InstallError(f'No Dart Sass release for architecture {platform.machine()!r}')
    return f'{system}-{arch}' + ('-musl' if _is_musl() else '')


def archive_name(version: str, tag: Optional[str] = None) -> str:
    tag = tag or platform_tag()
    ext = 'zip' if tag.startswith('windows') else 'tar.gz'
    return f'dart-sass-{version}-{tag}.{ext}'


def _find_pyproject(start: Path) -> Optional[Path]:
    for directory in (start, *start.parents):
        candidate = directory / 'pyproject.toml'
        if candidate.is_file():
            return candidate
    return None


def resolve_version(explicit: Optional[str] = None, start: Optional[Path] = None) -> str:
    """Determine which Dart Sass version to use (see the module docstring)."""
    if explicit:
        return explicit
    if os.environ.get('DART_SASS_VERSION'):
        return os.environ['DART_SASS_VERSION']
    pyproject = _find_pyproject((start or Path.cwd()).resolve())
    if pyproject is not None:
        with pyproject.open('rb') as fp:
            table = tomllib.load(fp).get('tool', {}).get(PYPROJECT_TABLE, {})
        if table.get('dart-sass-version'):
            return str(table['dart-sass-version'])
    return DEFAULT_DART_SASS_VERSION


def _expected_sha256(version: str, filename: str) -> str:
    try:
        return CHECKSUMS[filename]
    except KeyError:
        pass
    # not a version we ship checksums for: ask GitHub, which records a digest per asset
    request = urllib.request.Request(
        f'{API_URL}/{version}', headers={'Accept': 'application/vnd.github+json'})
    if token := os.environ.get('GITHUB_TOKEN'):
        request.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            assets = json.load(response).get('assets', [])
    except OSError as exc:
        raise InstallError(f'Could not look up the checksum for {filename}: {exc}') from exc
    for asset in assets:
        digest = asset.get('digest') or ''
        if asset.get('name') == filename and digest.startswith('sha256:'):
            return digest[len('sha256:'):]
    raise InstallError(f'No SHA-256 digest published for {filename} (use --no-verify to skip)')


def _download(url: str, destination: Path) -> str:
    sha256 = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response, destination.open('wb') as out:
            while chunk := response.read(1 << 16):
                sha256.update(chunk)
                out.write(chunk)
    except OSError as exc:
        raise InstallError(f'Download failed for {url}: {exc}') from exc
    return sha256.hexdigest()


def _extract(archive: Path, destination: Path) -> None:
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(destination)
    else:
        if not hasattr(tarfile, 'data_filter'):
            # Python before 3.11.4 cannot refuse members that would be written outside destination
            raise InstallError(
                'Extracting the archive safely needs Python 3.11.4 or later; upgrade Python, or '
                'install Dart Sass yourself (https://sass-lang.com/install) and put it on PATH.')
        with tarfile.open(archive) as tf:
            tf.extractall(destination, filter='data')


def _make_executable(release: Path) -> None:
    """Make sure the launcher and the Dart runtime it starts can be executed."""
    if platform.system() == 'Windows':
        return
    for path in (release / 'sass', release / 'src' / 'dart'):
        if not path.is_file():
            raise InstallError(f'Unexpected archive layout: {path} not found')
        path.chmod(path.stat().st_mode | 0o111)


def _verify(launcher: Path, version: str) -> None:
    """Run the freshly unpacked compiler and check that it reports the version we asked for."""
    try:
        # argument list, no shell; launcher is inside the archive we just unpacked
        result = subprocess.run(    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            [str(launcher), '--version'], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f'The installed Dart Sass does not run: {exc}') from exc
    reported = result.stdout.split()[:1]
    if result.returncode != 0 or reported != [version]:
        raise InstallError(
            f'The installed Dart Sass did not report version {version}: '
            f'{(result.stdout + result.stderr).strip() or "no output"}')


def _replace(unpacked: Path, target: Path) -> None:
    """
    Put ``unpacked`` in the place of ``target`` (on the same filesystem, so it is a rename).

    An existing ``target`` is kept until the replacement is in place, and restored if that fails.
    """
    backup = target.with_name(target.name + '.old')
    shutil.rmtree(backup, ignore_errors=True)
    had_previous = target.exists()
    if had_previous:
        target.rename(backup)
    try:
        unpacked.rename(target)
    except OSError:
        if had_previous:
            backup.rename(target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _link_executable(launcher: Path, bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if platform.system() == 'Windows':
        link = bin_dir / 'sass.cmd'
        link.write_text(f'@"{launcher}" %*\r\n')
    else:
        link = bin_dir / 'sass'
        link.unlink(missing_ok=True)
        link.symlink_to(launcher)
    return link


def install(
        version: Optional[str] = None,
        *,
        prefix: Optional[Path] = None,
        bin_dir: Optional[Path] = None,
        force: bool = False,
        verify: bool = True,
) -> Path:
    """
    Install Dart Sass and return the path of the ``sass`` executable that was linked.
    """
    version = resolve_version(version)
    in_venv = sys.prefix != sys.base_prefix
    if prefix is None:
        if not in_venv:
            raise InstallError(
                'Not running in a virtualenv; activate one, or pass --prefix and --bin-dir.')
        prefix = Path(sys.prefix)
    if bin_dir is None:
        if not in_venv:
            raise InstallError('Not running in a virtualenv; pass --bin-dir.')
        bin_dir = Path(sysconfig.get_path('scripts'))

    filename = archive_name(version)
    target = Path(prefix) / 'dart-sass' / version
    launcher = target / 'dart-sass' / ('sass.bat' if platform.system() == 'Windows' else 'sass')

    if force or not launcher.exists():
        expected = _expected_sha256(version, filename) if verify else None
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp, \
                tempfile.TemporaryDirectory(dir=target.parent, prefix='.staging-') as staging:
            archive = Path(tmp) / filename
            actual = _download(f'{RELEASES_URL}/{version}/{filename}', archive)
            if expected is not None and actual != expected:
                raise InstallError(
                    f'Checksum mismatch for {filename}: expected {expected}, got {actual}')
            # unpacked beside the target, checked, and only then put in place
            unpacked = Path(staging) / 'unpacked'
            _extract(archive, unpacked)
            release = unpacked / 'dart-sass'
            _make_executable(release)
            _verify(release / launcher.name, version)
            _replace(unpacked, target)

    return _link_executable(launcher.resolve(), Path(bin_dir))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m django_sass_finder.install',
        description='Install the Dart Sass compiler into the current virtualenv.')
    parser.add_argument('--version', help='Dart Sass version (default: from pyproject.toml, or '
                                          f'{DEFAULT_DART_SASS_VERSION})')
    parser.add_argument('--prefix', type=Path, help='install under PREFIX/dart-sass (default: sys.prefix)')
    parser.add_argument('--bin-dir', type=Path, help='directory to link `sass` into (default: scripts dir)')
    parser.add_argument('--force', action='store_true', help='reinstall even if already present')
    parser.add_argument('--no-verify', action='store_true', help='skip the SHA-256 check')
    args = parser.parse_args(argv)
    try:
        exe = install(args.version, prefix=args.prefix, bin_dir=args.bin_dir,
                      force=args.force, verify=not args.no_verify)
    except InstallError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(f'Dart Sass {resolve_version(args.version)} installed: {exe}')
    return 0


if __name__ == '__main__':      # pragma: no cover
    sys.exit(main())
