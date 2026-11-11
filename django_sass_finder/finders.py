# -*- coding: utf-8 -*-
import logging
import stat
import threading
import time
from pathlib import Path

from django.apps import apps

from django.conf import settings
from django.contrib.staticfiles.finders import AppDirectoriesFinder, BaseFinder
from django.core.checks import Error
from django.core.files.storage import FileSystemStorage

from .compilers import get_compiler, map_path, read_map_sources

logger = logging.getLogger(__name__)

__all__ = (
    'ScssFinder',
)


class ScssFinder(BaseFinder):
    """
    Finds .scss files specified in SCSS_ROOT and SCSS_COMPILE settings with globs.
    """

    def _path_is_parent(self, path: Path) -> bool:
        try:
            self.css_compile_dir.relative_to(path)
            return True
        except ValueError:
            return False

    def _path_in_staticfiles(self):
        for static_dir in getattr(settings, 'STATICFILES_DIRS', []):
            if self._path_is_parent(Path(static_dir).resolve()):
                self._serve_static = getattr(settings, 'CSS_SERVE_STATIC', False)
                return

    def _path_in_appdirectories(self):
        if not self.apps_static_checked and apps.apps_ready and self._serve_static:
            try:
                app_configs = apps.get_app_configs()
                for app_config in app_configs:
                    if self._path_is_parent(Path(app_config.path) / AppDirectoriesFinder.source_dir):
                        self._serve_static = getattr(settings, 'CSS_SERVE_STATIC', False)
                        return
            finally:
                self.apps_static_checked = True

    def __init__(self, app_names=None, *args, **kwargs):
        self.scss_compile = getattr(settings, 'SCSS_COMPILE', ['**/*.scss'])
        self.root = Path(settings.SCSS_ROOT)
        css_compile_dir = getattr(settings, 'CSS_COMPILE_DIR', self.root)
        self.css_compile_dir = Path(css_compile_dir).resolve()
        self.output_style = getattr(settings, 'CSS_STYLE', '')
        self.css_map = getattr(settings, 'CSS_MAP', False)
        self.include_paths = getattr(settings, 'SCSS_INCLUDE_PATHS', [])
        self.storage = FileSystemStorage(location=self.css_compile_dir)
        # the compiler backend: 'dart' (default), 'libsass' or a dotted path to a Compiler class
        self.compiler_name = getattr(settings, 'SCSS_COMPILER', 'dart')
        executable = getattr(settings, 'SCSS_EXECUTABLE', None)
        self.compiler = get_compiler(self.compiler_name, **({'executable': str(executable)} if executable else {}))
        # lookups arrive in bursts (one per static file on a page); scan the sources at most this often
        self.rescan_interval = getattr(settings, 'SCSS_RESCAN_INTERVAL', 0.5)
        self._lock = threading.RLock()
        self._last_scan = None

        # by default, we serve our own files
        self._serve_static = True
        # we can check staticfiles immediately
        self._path_in_staticfiles()
        # apps probably aren't ready yet
        self.apps_static_checked = False
        self._path_in_appdirectories()

        # scss file -> {file it was compiled from or read while compiling: its mtime then}
        self.source_cache = {}
        # path as requested through staticfiles (css) -> compiled file
        self.files_cache = {}

    @property
    def serve_static(self):
        self._path_in_appdirectories()
        return self._serve_static

    def check(self, **kwargs):
        """
        Checks if ScssFinder is configured correctly.

        SCSS_COMPILE should contain valid files, and the compiler must be usable.
        """
        errors = []

        for scss_item in self.scss_compile:
            for _ in self.root.glob(scss_item):
                break
            else:
                errors.append(Error(
                    f'{scss_item} returned no files in {self.scss_compile}.',
                    id='sass.E001'
                ))

        errors.extend(self.compiler.check())

        styles = self.compiler.output_styles
        if self.output_style and styles and self.output_style not in styles:
            errors.append(Error(
                f'CSS_STYLE {self.output_style!r} is not supported by the {self.compiler_name!r} compiler.',
                hint=f'Use one of: {", ".join(styles)}.',
                id='sass.E003'
            ))

        return errors

    def output_path(self, scss_file, makedirs=False):
        # determine where the file will be generated, and ensure path exists if possible
        outpath = self.css_compile_dir / scss_file.relative_to(self.root).parent
        if makedirs:
            outpath.mkdir(parents=True, exist_ok=True)
        # add the filename to the output path
        return outpath / (scss_file.stem + '.css')

    @staticmethod
    def _stat(path):
        try:
            return path.stat()
        except OSError:
            return None     # usually FileNotFoundError

    def _snapshot(self, dependencies):
        """Current modification times of the files a compilation read."""
        mtimes = {}
        for path in dependencies:
            path_stat = self._stat(path)
            if path_stat is not None:
                mtimes[path] = path_stat.st_mtime
        return mtimes

    def _is_current(self, scss_file, outpath):
        """True if outpath is up to date with its source and everything that source reads."""
        out_stat = self._stat(outpath)
        if out_stat is None:
            return False
        mapfile = map_path(outpath)
        if self.css_map and self._stat(mapfile) is None:
            return False

        known = self.source_cache.get(scss_file)
        if known is not None:
            return all(
                (path_stat := self._stat(path)) is not None and path_stat.st_mtime == mtime
                for path, mtime in known.items()
            )

        # not compiled by this process yet: the source map from an earlier run, if any,
        # tells which files were read. Without one we cannot know, so we must compile.
        dependencies = read_map_sources(mapfile) if self.css_map else None
        if not dependencies:
            return False
        mtimes = self._snapshot(dependencies | {scss_file})
        if len(mtimes) != len(dependencies | {scss_file}):
            return False        # something it read has gone
        if any(mtime >= out_stat.st_mtime for mtime in mtimes.values()):
            return False
        self.source_cache[scss_file] = mtimes
        return True

    def _compile_file(self, scss_file, outpath):
        dependencies = self.compiler.compile(
            scss_file, outpath,
            source_map=self.css_map,
            output_style=self.output_style,
            include_paths=[Path(path) for path in self.include_paths],
        )
        # record only after a successful compile, so a failing file is retried next time
        self.source_cache[scss_file] = self._snapshot(dependencies | {scss_file})

    def compile_scss(self):
        """
        Search for and compile all scss files that need it.

        Lookups arrive in bursts, so a scan is skipped if one finished less than
        SCSS_RESCAN_INTERVAL seconds ago.
        """
        with self._lock:
            if self._last_scan is not None and time.monotonic() - self._last_scan < self.rescan_interval:
                return
            self._scan()
            self._last_scan = time.monotonic()

    def _scan(self):
        checked = set()
        files_cache = {}

        for scss_item in self.scss_compile:
            for scss_file in self.root.glob(scss_item):
                if scss_file in checked:
                    continue        # matched by more than one pattern
                if scss_file.name.startswith('_'):
                    continue        # a partial, only meant to be loaded by other files
                scss_stat = self._stat(scss_file)
                if not scss_stat or not stat.S_ISREG(scss_stat.st_mode):
                    continue        # not is_file()

                checked.add(scss_file)
                outpath = self.output_path(scss_file, makedirs=True)
                files_cache[outpath.relative_to(self.css_compile_dir).as_posix()] = outpath
                if not self._is_current(scss_file, outpath):
                    self._compile_file(scss_file, outpath)

        # swap in the new mapping in one go: lookups outside the lock never see a half built one
        self.files_cache = files_cache

        # walk the cache and check for any previously present files
        removed = [scss_file for scss_file in self.source_cache if scss_file not in checked]
        # and remove them from cache and unlink the target files
        for scss_file in removed:
            del self.source_cache[scss_file]
            outpath = self.output_path(scss_file)
            for stale in (outpath, map_path(outpath)):
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    pass

    def find(self, path, find_all=False):
        """
        Run the compiler and see if was collected
        """
        self.compile_scss()
        if self.serve_static and path in self.files_cache:
            path = self.files_cache[path].as_posix()
            return [path] if find_all else path
        return []

    def list(self, ignore_patterns):
        """
        Compile then list the .css files.
        """
        self.compile_scss()
        if self.serve_static and self.files_cache:
            for path, _ in self.files_cache.items():
                yield str(path), self.storage
