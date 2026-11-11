# Changelog

## 3.0.0

Dart Sass support, a new compiler interface, fixes for current Django, and a project refresh
bringing packaging, dependencies and tests up to date.

### Breaking changes

- **Dart Sass is now the default compiler** and supports the modern module system (`@use`,
  `@forward`). Install it into the virtualenv with `python -m django_sass_finder.install`.
  LibSass is deprecated upstream and is now an optional backend:
  `pip install "django_sass_finder[libsass]"` and `SCSS_COMPILER = 'libsass'`.
- `CSS_STYLE` accepts `expanded` and `compressed` with Dart Sass; `nested` and `compact` remain
  libsass-only. Django's system checks report an unsupported style (`sass.E003`).
- Source maps are now written as `{name}.css.map` (previously `{name}.map`).
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
- `SCSS_RESCAN_INTERVAL` setting. Lookups arrive in bursts; sources are scanned at most this often.
- System check `sass.E002` for a missing or unusable compiler.
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
- Changing a file loaded by a source with `@import` or `@use` did not recompile it; only the
  modification time of the source itself was checked.
- Concurrent requests (the development server is threaded) could briefly find no compiled files
  while another request was rescanning, and compiled the same file at the same time.
- A failing compile truncated the existing CSS output first.
- A file matched by more than one `SCSS_COMPILE` pattern was compiled more than once.
- Output and source map of a deleted source are both removed.
- Malformed author email address in the package metadata.
- README: the setting is `STATICFILES_DIRS`, not `STATICFILES_ROOT`.
