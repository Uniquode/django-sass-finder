# -*- coding: utf-8 -*-
import stat
from pathlib import Path

import sass

from django.conf import settings
from django.contrib.staticfiles.finders import FileSystemFinder
from django.core.checks import Error

__all__ = (
    'ScssFinder',
)


class ScssFinder(FileSystemFinder):
    """
    Finds .scss files specified in SCSS_ROOT and SCSS_COMPILE settings with globs.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scss_compile = getattr(settings, 'SCSS_COMPILE', ['**/*.scss'])
        self.root = Path(settings.SCSS_ROOT)
        self.css_compile_dir = Path(settings.CSS_COMPILE_DIR)
        self.output_style = getattr(settings, 'CSS_STYLE', '')
        self.css_map = getattr(settings, 'CSS_MAP', False)
        self.source_cache = {}

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
        for scss_item in self.scss_compile:
            for scss_file in self.root.glob(scss_item):
                try:
                    scss_stat = scss_file.stat()
                except OSError:
                    continue        # usually FileNotFoundError
                if not stat.S_ISREG(scss_stat.st_mode):
                    continue        # not is_file()

                # mark this as checked
                checked.append(scss_file)
                try:
                    cached = self.source_cache[scss_file]
                    if scss_stat.st_mtime == cached:
                        continue        # unchanged, skip
                except KeyError:
                    pass

                outpath = self.output_path(scss_file, makedirs=True)
                mappath = outpath.parent / (outpath.stem + '.map')
                # generate the css
                with outpath.open('w+') as outfile:
                    sass_args = {'filename': str(scss_file)}
                    if self.css_map:
                        sass_args['source_map_filename'] = str(mappath)
                    if self.output_style:
                        sass_args['output_style'] = self.output_style
                    result = sass.compile(**sass_args)
                    if isinstance(result, tuple):
                        # if source map was requested, sass.compile returns a tuple: result, source map
                        # we're not really interested in the source map other than generating it
                        result, _ = result
                    outfile.write(result)
                # add to or update the cache
                self.source_cache[scss_file] = scss_stat.st_mtime

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
        Run the compiler and leave it up to the filesystemfinder to locate it
        """
        self.compile_scss()
        return super().find(path, all=all)

    def list(self, ignore_patterns):
        """
        Compile then list the .css files.
        """
        self.compile_scss()
        return super().list(ignore_patterns)
