# Django Sass Finder
A static files finder for Django that compiles Sass files

## Installation
### WARNING: MAKE SURE YOU HAVE NO OTHER SASS PACKAGES INSTALLED!
Run `pip install django_sass_finder` to add this module to your virtualenv, then install the
Sass compiler (see below), and add the finder to the list of your static file finders:

```python
STATICFILES_FINDERS = [
    # add the default Django finders as this setting will override the default
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    # our finder
    'django_sass_finder.finders.ScssFinder',
]
```
There is no need to add django_sass_finder into `settings.INSTALLED_APPS`.

### The compiler
By default the finder compiles with [Dart Sass](https://sass-lang.com/dart-sass/), the reference
implementation of Sass, which supports the modern `@use`/`@forward` module system. It is a
separate program rather than a Python package, so install it into your virtualenv with:

```shell
python -m django_sass_finder.install
```

This downloads the official release for your platform from GitHub, verifies its SHA-256
checksum, and links `sass` into the virtualenv's `bin` directory, so it is on `PATH` whenever the
virtualenv is active. The finder also finds it there when you run the virtualenv's python directly.
Any other Dart Sass on `PATH` (for example from `npm install sass`) works too.

The version installed is, in order of precedence: `--version` on the command line, the
`DART_SASS_VERSION` environment variable, `dart-sass-version` in your `pyproject.toml`
(searching upwards from the current directory), or the version this package was tested with:

```toml
[tool.django-sass-finder]
dart-sass-version = "1.108.1"
```

Run the install command again after changing the version (and in CI, Docker builds, etc.).

#### LibSass (legacy)
[LibSass](https://sass-lang.com/blog/libsass-is-deprecated/) is deprecated, does not support `@use`
and has known security issues. It is still available to ease migration:
`pip install "django_sass_finder[libsass]"` and set `SCSS_COMPILER = 'libsass'`.

## Settings
The following additional (with examples) settings are used by this staticfiles finder:

```python
BASE_DIR = ...

SCSS_ROOT = BASE_DIR / 'scss'   # required: where the .scss files are sourced
SCSS_COMPILE = [                # a list of filename pattern to search for within SCSS_ROOT
    'site.scss',                # default is **/*.scss (all scss source files in and below SCSS_ROOT)
    'admin/admin.scss',         # files whose name starts with an underscore are partials: never compiled on their own
]
SCSS_INCLUDE_PATHS = [          # optional: scss compiler include (load) paths (default = empty)
    BASE_DIR / 'node_modules'
]
SCSS_COMPILER = 'dart'              # optional: 'dart' (default), 'libsass' or a dotted path to a Compiler class
SCSS_EXECUTABLE = None              # optional: path of the sass executable (default: search for it)
SCSS_RESCAN_INTERVAL = 0.5          # optional: look for changed sources at most this often (seconds)
CSS_STYLE = 'compressed'            # optional: output format, 'expanded' or 'compressed'
                                    #           (libsass also has 'nested' and 'compact')
CSS_MAP = True                      # optional: generate a source map, next to the css as {name}.css.map
CSS_COMPILE_DIR = BASE_DIR / 'static' / 'css'   # optional: The target directories for the compiled .css
STATICFILES_DIRS = [                            # this should be at or above the CSS_COMPILE_DIR
    BASE_DIR / 'static'                         # but targetting {app}/static should also work
]
```

`BASE_DIR` and variants above are `pathlib.Path` objects, but path strings can also be used.

If CSS_COMPILE_DIR is not set, the SCSS_ROOT is used and css (and map) files are generated next to the
scss source files.

Django's system checks (`manage.py check`) report a missing compiler, an unsupported `CSS_STYLE`, and
`SCSS_COMPILE` patterns that match no files.

## Usage
This module dynamically compiles to target .css files, and recompiles them on demand whenever
the source files are updated. A file is recompiled when it, or any file it loads (`@use`, `@import`),
changes. Without `CSS_MAP` a restarted server cannot tell what an earlier run loaded, so it compiles
every file once at start up; with `CSS_MAP` it reads that back from the source maps.

The `collectstatic` management command compiles these and copies them into STATIC_ROOT along with
the usual files from STATICFILES_DIRS and app `static` directories.

The development server is perfectly able to serve these from STATICFILES_DIRS without the need
to run `collectstatic`.

## Continuous integration
Install the package, then run the same command as above, before anything that compiles:

```yaml
      - run: uv sync --locked
      - run: uv run python -m django_sass_finder.install
```

(or `pip install .` followed by `python -m django_sass_finder.install`). No separate setup action is
needed, and the archive is small (about 4 MB).

## License
This package is licensed under the MIT license.
