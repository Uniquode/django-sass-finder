"""
Sass compiler backends.

A backend turns one Sass source file into a CSS file (and optionally a source map), and
reports every file it read while doing so, so the finder knows when to recompile.
"""
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Collection, Optional, Sequence
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from django.core.checks import CheckMessage
from django.utils.module_loading import import_string

__all__ = (
    'CompileError',
    'Compiler',
    'CompilerUnavailable',
    'get_compiler',
    'map_path',
    'read_map_sources',
)

BUILTIN = {
    'dart': 'django_sass_finder.compilers.dart.DartSassCompiler',
    'libsass': 'django_sass_finder.compilers.libsass.LibsassCompiler',
}


class CompileError(Exception):
    """The Sass source could not be compiled."""


class CompilerUnavailable(CompileError):
    """The compiler itself is missing or unusable."""


def map_path(output: Path) -> Path:
    """Where the source map of ``output`` lives (``site.css`` -> ``site.css.map``)."""
    return output.with_name(output.name + '.map')


def read_map_sources(mapfile: Path) -> Optional[frozenset]:
    """
    The set of files listed in a source map, or None if it cannot be read.

    Source URLs are relative to the map's directory, or ``file:`` URLs.
    """
    try:
        sources = json.loads(mapfile.read_text(encoding='utf-8'))['sources']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    found = set()
    for source in sources:
        parsed = urlparse(source)
        if parsed.scheme == 'file':
            path = Path(url2pathname(parsed.path))
        elif not parsed.scheme or (len(parsed.scheme) == 1 and os.name == 'nt'):    # drive letter
            path = mapfile.parent / unquote(source)
        else:
            continue        # data:, stdin, ... nothing on disk to watch
        found.add(Path(os.path.normpath(path)))
    return frozenset(found)


class Compiler(ABC):
    """
    Interface of a Sass compiler backend.

    Custom backends may be selected with ``SCSS_COMPILER = 'dotted.path.to.Class'``.
    """
    #: output styles this compiler accepts for CSS_STYLE
    output_styles: Collection[str] = ()

    @abstractmethod
    def check(self) -> Sequence[CheckMessage]:
        """Report problems that would stop this compiler working (for the system checks)."""

    @abstractmethod
    def compile(
            self,
            source: Path,
            output: Path,
            *,
            source_map: bool = False,
            output_style: str = '',
            include_paths: Sequence[Path] = (),
    ) -> frozenset:
        """
        Compile ``source`` to the file ``output`` (the directory exists).

        If ``source_map`` is true, also write ``map_path(output)``.
        Returns every file read, ``source`` included. Raises CompileError on failure.
        """


def get_compiler(spec: str = 'dart', **options) -> Compiler:
    """Instantiate the backend named ``spec``: 'dart', 'libsass', or a dotted class path."""
    return import_string(BUILTIN.get(spec, spec))(**options)
