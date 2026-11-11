"""
Dart Sass, the reference implementation of Sass, run as a subprocess.

Install it into the virtualenv with ``python -m django_sass_finder.install``; any ``sass``
on ``PATH`` that is Dart Sass (for example from npm) works as well.
"""
import logging
import re
import shutil
import subprocess
import sysconfig
from pathlib import Path
from typing import Optional, Sequence

from django.core.checks import Error

from . import CompileError, Compiler, CompilerUnavailable, map_path, read_map_sources

__all__ = (
    'DartSassCompiler',
)

logger = logging.getLogger('django_sass_finder')

VERSION_RE = re.compile(r'^\d+\.\d+\.\d+')
TIMEOUT = 120
INSTALL_HINT = 'run `python -m django_sass_finder.install` in your virtualenv'


class DartSassCompiler(Compiler):
    output_styles = ('expanded', 'compressed')

    def __init__(self, executable: Optional[str] = None):
        self.executable = executable
        self._resolved: Optional[str] = None

    def find_executable(self) -> str:
        """Locate ``sass``: the configured path, this environment's scripts dir, then PATH."""
        if self._resolved:
            return self._resolved
        if self.executable:
            candidates = [self.executable]
        else:
            scripts = sysconfig.get_path('scripts')
            candidates = [shutil.which('sass', path=scripts), shutil.which('sass')]
        for candidate in candidates:
            if candidate and (version := self.version(candidate)):
                logger.debug('Using Dart Sass %s at %s', version, candidate)
                self._resolved = candidate
                return candidate
        raise CompilerUnavailable(f'Dart Sass not found: {INSTALL_HINT}')

    @staticmethod
    def version(executable: str) -> Optional[str]:
        try:
            result = subprocess.run(
                [executable, '--version'], capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return None
        output = result.stdout.strip()
        # Dart Sass prints just its version; Ruby Sass and others do not
        return output.split()[0] if result.returncode == 0 and VERSION_RE.match(output) else None

    def check(self):
        try:
            self.find_executable()
        except CompilerUnavailable as exc:
            return [Error(str(exc), id='sass.E002',
                          hint='Or set SCSS_COMPILER to another backend, or SCSS_EXECUTABLE to a path.')]
        return []

    def compile(self, source, output, *, source_map=False, output_style='', include_paths=()):
        args = [
            self.find_executable(),
            f'--style={output_style or "expanded"}',
            '--no-color',
            '--no-error-css',       # never leave error CSS behind as if it were the result
            '--source-map',         # always: the map tells us which files were read
            '--source-map-urls=relative',
        ]
        args += [f'--load-path={path}' for path in include_paths]
        args += [f'{source}:{output}']
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CompilerUnavailable(f'Could not run Dart Sass: {exc}') from exc
        if result.returncode != 0:
            raise CompileError(f'Compiling {source} failed:\n{result.stderr.strip()}')
        if result.stderr.strip():
            logger.warning('Dart Sass, compiling %s:\n%s', source, result.stderr.strip())

        mapfile = map_path(output)
        dependencies = read_map_sources(mapfile) or frozenset()
        if not source_map:
            mapfile.unlink(missing_ok=True)
            # drop the now dangling reference to the map
            css = output.read_text(encoding='utf-8')
            output.write_text(re.sub(r'\n?/\*# sourceMappingURL=.*?\*/\s*$', '\n', css),
                              encoding='utf-8')
        return dependencies | {Path(source)}
