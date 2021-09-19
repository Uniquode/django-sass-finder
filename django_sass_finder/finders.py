# -*- coding: utf-8 -*-
import stat
from pathlib import Path

import sass
from django.apps import apps

from django.conf import settings
from django.contrib.staticfiles.finders import AppDirectoriesFinder, BaseFinder
from django.core.checks import Error
from django.core.files.storage import FileSystemStorage

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
        self.css_compile_dir = Path(settings.CSS_COMPILE_DIR).resolve()
        self.output_style = getattr(settings, 'CSS_STYLE', '')
        self.css_map = getattr(settings, 'CSS_MAP', False)
        self.include_paths = getattr(settings, 'SCSS_INCLUDE_PATHS', [])
        self.storage = FileSystemStorage(location=self.css_compile_dir)

        # by default, we serve our own files
        self._serve_static = True
        # we can check staticfiles immediately
        self._path_in_staticfiles()
        # apps probably aren't ready yet
        self.apps_static_checked = False
        self._path_in_appdirectories()

        self.source_cache = {}
        self.files_cache = {}

    @property
    def serve_static(self):
        self._path_in_appdirectories()
        return self._serve_static

    def check(self, **kwargs):
        """
        Checks if ScssFinder is configured correctly.

        SCSS_COMPILE should contain valid files.
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

        return errors

    def output_path(self, scss_file, makedirs=False):
        # determine where the file will be generated, and ensure path exists if possible
        outpath = self.css_compile_dir / scss_file.relative_to(self.root).parent
        if makedirs:
            outpath.mkdir(parents=True, exist_ok=True)
        # add the filename to the output path
        return outpath / (scss_file.stem + '.css')

    def compile_scss(self):
        # search for and compile all scss files
        checked = []
        self.files_cache.clear()

        def path_stat(path):
            try:
                return path.stat()
            except OSError:
                pass    # usually FileNotFoundError

        for scss_item in self.scss_compile:
            for scss_file in self.root.glob(scss_item):
                scss_stat = path_stat(scss_file)
                if not scss_stat:
                    continue
                if not stat.S_ISREG(scss_stat.st_mode):
                    continue        # not is_file()

                # mark this as checked
                checked.append(scss_file)
                # add it to the files cache
                outpath = self.output_path(scss_file, makedirs=True)
                mappath = outpath.parent / (outpath.stem + '.map')

                relpath = outpath.relative_to(self.css_compile_dir)
                self.files_cache[relpath.as_posix()] = outpath
                try:
                    cached_mtime = self.source_cache[scss_file]
                    if scss_stat.st_mtime == cached_mtime:
                        continue        # unchanged, skip
                except KeyError:
                    pass

                # new timestamp
                cached_mtime = scss_stat.st_mtime
                out_stat = path_stat(outpath)
                map_stat = path_stat(mappath)
                if out_stat is not None and out_stat.st_mtime > cached_mtime:
                    # output css file is up to date, if we reqested a map, make sure it also does not need update
                    if not self.css_map or (map_stat is not None and map_stat.st_mtime > cached_mtime):
                        self.source_cache[scss_file] = cached_mtime
                        continue

                # generate the css
                with outpath.open('w+') as outfile:
                    sass_args = {'filename': str(scss_file)}
                    if self.css_map:
                        sass_args['source_map_filename'] = str(mappath)
                    if self.include_paths:
                        sass_args['include_paths'] = [str(path) for path in self.include_paths]
                    if self.output_style:
                        sass_args['output_style'] = self.output_style
                    result = sass.compile(**sass_args)
                    if isinstance(result, tuple):
                        # if source map was requested, sass.compile returns a tuple: result, source map
                        # we're not really interested in the source map other than generating it
                        result, _ = result
                    outfile.write(result)
                # add to or update the cache
                self.source_cache[scss_file] = cached_mtime

        # walk the cache and check for any previously present files
        removed = [scss_file for scss_file, _ in self.source_cache.items() if scss_file not in checked]
        # and remove them from cache and unlink the target files
        for scss_file in removed:
            del self.source_cache[scss_file]
            outpath = self.output_path(scss_file)
            try:
                outpath.unlink(missing_ok=True)
            except OSError:
                pass

    def find(self, path, all=False):
        """
        Run the compiler and see if was collected
        """
        self.compile_scss()
        if self.serve_static and path in self.files_cache:
            path = self.files_cache[path].as_posix()
            return [path] if all else path
        return []

    def list(self, ignore_patterns):
        """
        Compile then list the .css files.
        """
        self.compile_scss()
        if self.serve_static and self.files_cache:
            for path, _ in self.files_cache.items():
                yield str(path), self.storage
