"""
LibSass (the ``libsass`` package), the legacy backend.

LibSass is deprecated upstream and does not understand the modern module system
(``@use``, ``@forward``); it is supported to ease migration only.
"""
from pathlib import Path

from django.core.checks import Error

from . import CompileError, Compiler, CompilerUnavailable, map_path, read_map_sources

__all__ = (
    'LibsassCompiler',
)


class LibsassCompiler(Compiler):
    output_styles = ('nested', 'expanded', 'compact', 'compressed')

    @staticmethod
    def _sass():
        try:
            import sass
        except ImportError as exc:
            raise CompilerUnavailable(
                'The libsass package is not installed: pip install "django-dart-sass-finder[libsass]"'
            ) from exc
        return sass

    def check(self):
        try:
            self._sass()
        except CompilerUnavailable as exc:
            return [Error(str(exc), id='sass.E002')]
        return []

    def compile(self, source, output, *, source_map=False, output_style='', include_paths=()):
        sass = self._sass()
        mapfile = map_path(output)
        kwargs = {
            'filename': str(source),
            'output_filename_hint': str(output),
            'source_map_filename': str(mapfile),    # always: the map lists the files read
            'omit_source_map_url': not source_map,
        }
        if include_paths:
            kwargs['include_paths'] = [str(path) for path in include_paths]
        if output_style:
            kwargs['output_style'] = output_style
        try:
            css, map_json = sass.compile(**kwargs)
        except sass.CompileError as exc:
            raise CompileError(f'Compiling {source} failed:\n{exc}') from exc
        output.write_text(css, encoding='utf-8')
        # written either way so the dependencies can be read back, removed if unwanted
        mapfile.write_text(map_json, encoding='utf-8')
        dependencies = read_map_sources(mapfile) or frozenset()
        if not source_map:
            mapfile.unlink(missing_ok=True)
        return dependencies | {Path(source)}
