# Changelog

## 3.0.0

Published on PyPI as `django-dart-sass-finder` (the original `django-sass-finder` is a separate
project). The import name is unchanged: `django_sass_finder`, so existing settings keep working.
Uninstall `django-sass-finder` first, as both install the same module.

Dart Sass support, a new compiler interface, fixes for current Django, and a project refresh
bringing packaging, dependencies and tests up to date.

### Breaking changes

- **Dart Sass is now the default compiler** and supports the modern module system (`@use`,
  `@forward`). Install it into the virtualenv with `python -m django_sass_finder.install`.
  LibSass is deprecated upstream and is now an optional backend:
  `pip install "django-dart-sass-finder[libsass]"` and `SCSS_COMPILER = 'libsass'`.
- `CSS_STYLE` accepts `expanded` and `compressed` with Dart Sass; `nested` and `compact` remain
  libsass-only. Django's system checks report an unsupported style (`sass.E003`).
- The default output style is Dart Sass's `expanded`; libsass defaulted to `nested`. Set
  `CSS_STYLE` to keep a specific format.
- Compile errors are raised as `django_sass_finder.compilers.CompileError` rather than
  `sass.CompileError`.
- Source maps are now written as `{name}.css.map` (previously `{name}.map`). The `.map` files
  written by earlier versions are not removed; delete them by hand.
- Files whose name starts with an underscore are Sass partials and are no longer compiled on
  their own.
- Requires Python 3.11 or later (previously 3.7+), Django 5.2 or later (previously 3.2), and no
  longer depends on libsass.
- Removed support for Python 3.7 to 3.10 and for Django 3.0 to 4.x.

### Added

- `python -m django_sass_finder.install` installs a checksum-verified Dart Sass release into the
  virtualenv, for the running platform. The version is chosen with `--version`,
  `DART_SASS_VERSION`, or `dart-sass-version` in the `[tool.django-sass-finder]` table of
  `pyproject.toml`.
- Pluggable compiler backends (`SCSS_COMPILER`, `SCSS_EXECUTABLE`), including custom ones via a
  dotted path to a `django_sass_finder.compilers.Compiler` subclass.
- Without `CSS_MAP`, a restarted server compiles every file once, because it cannot tell what an
  earlier run loaded; with `CSS_MAP` it reads the dependencies back from the source maps.
- Dart Sass warnings (for example the deprecation of `@import`) are logged to the
  `django_sass_finder` logger at warning level.
- `SCSS_RESCAN_INTERVAL` setting. Lookups arrive in bursts; sources are scanned at most this often.
- System checks `sass.E002` for a missing or unusable compiler and `sass.E004` for a
  `SCSS_COMPILER` that cannot be loaded. `sass.E001` also reports a pattern that matches only
  partials.
- GitHub Actions workflow (`.github/workflows/test.yml`) running the test suite across Python
  3.11 to 3.15 with both compiler backends.

### Changed

- **Packaging:** switched from Poetry to [uv](https://docs.astral.sh/uv/). Metadata now lives in a
  standard PEP 621 `[project]` table, development dependencies in a `[dependency-groups]` table,
  and the build backend is `uv_build`. `poetry.lock` is replaced by `uv.lock`.
- **Tests:** updated for current pytest (9.0 or later) and run against every available compiler
  backend. The unmaintained `pytest-pythonpath` plugin is removed; it caused a
  `PytestRemovedIn10Warning`.

### Fixed

- `find()` took an `all` argument, which current Django no longer passes (it calls
  `find(path, find_all=...)`), so every lookup through `django.contrib.staticfiles` raised
  `TypeError`. It is now `find_all`.
- A file changed or removed while it was being compiled could leave stale CSS marked as current.
- A failure to remove the output of a deleted source is logged as a warning, not ignored silently.
- A source map that is valid JSON but has no list of sources no longer raises; the file is compiled again.
- Changing a file loaded by a source with `@import` or `@use` did not recompile it; only the
  modification time of the source itself was checked.
- Concurrent requests (the development server is threaded) could briefly find no compiled files
  while another request was rescanning, and compiled the same file at the same time.
- A failing compile truncated the existing CSS output first.
- A file matched by more than one `SCSS_COMPILE` pattern was compiled more than once.
- Output and source map of a deleted source are both removed.
- Malformed author email address in the package metadata.
- README: the setting is `STATICFILES_DIRS`, not `STATICFILES_ROOT`.
