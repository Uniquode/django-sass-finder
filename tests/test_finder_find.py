# -*- coding: utf-8 -*-
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.test.utils import override_settings

from django_sass_finder.compilers import CompileError, get_compiler
from django_sass_finder.finders import ScssFinder


FIXTURE_CONTENT = {
    'site.scss': """// site specific css
$fore-color: midnightblue;
$special-font-family: "Noto Sans JP", Hevetica, serif;

h1, h2, h3, h4, h5, h6 {
  font-family: $special-font-family;
  font-weight: bold;
  color: $fore-color;
}
""",
    'admin/admin-site.scss': """// admin tweaks
.field-test { line-height: 1.2em; }
""",
    'apps/extra.scss': """
$bg-color: rgba(0, 0, 0, 0.4);
$bg-image: "../images/default-bg-image.jpg";
$bg-blend: soft-light; 

body, html { height: 100%; }

* { box-sizing: border-box; }

body {
  .bg-image {
    background-color: $bg-color;
    background-image: $bg-image;
    height: 100%;
    background-position: center;
    background-repeat: no-repeat;
    background-size: cover;
    background-blend-mode: $bg-blend;
    position: relative;
  }
  
  .bg-text {
    position: absolute;
    top: 10vh;
    right: 20vh;
    padding: 5rem;
    opacity: 100%;
    color: white;
    font: 22px Arial, sans-serif;
    text-align: center;
    z-index: 99;
  }
}
"""
}

CSS_NAMES = [name.rsplit('.', maxsplit=1)[0] + '.css' for name in FIXTURE_CONTENT]


@pytest.fixture(params=['dart', 'libsass'])
def backend(request):
    """The name of each compiler backend; skipped if unavailable (a failure if required)."""
    problems = get_compiler(request.param).check()
    if problems:
        message = f'{request.param} compiler unavailable: {problems[0].msg}'
        if os.environ.get('SCSS_TEST_REQUIRE_ALL'):
            pytest.fail(message)
        pytest.skip(message)
    return request.param


@pytest.fixture
def project(tmp_path, backend):
    """A scss source tree, with the settings pointing at it. Yields the base directory."""
    base_dir = tmp_path.resolve()
    scss_root = base_dir / 'scss'
    for filename, scss_content in FIXTURE_CONTENT.items():
        scss_file: Path = scss_root / filename
        scss_file.parent.mkdir(parents=True, exist_ok=True)
        scss_file.write_text(scss_content)
    with override_settings(
            SCSS_COMPILER=backend,
            SCSS_ROOT=scss_root,
            SCSS_COMPILE=['**/*.scss'],
            SCSS_INCLUDE_PATHS=[base_dir / 'node_modules'],
            SCSS_RESCAN_INTERVAL=0,
            # use a separate storage for our files (not staticfiles or appdirs)
            CSS_COMPILE_DIR=base_dir / 'output' / 'css',
            STATICFILES_DIRS=[base_dir / 'static'],
            CSS_STYLE='expanded',
            CSS_MAP=True,
            STATIC_ROOT=base_dir / 'static_root'):
        yield base_dir


def write_source(project, name, content):
    """
    Write a source file with a controlled mtime, so tests do not depend on clock granularity:
    new files look old (already there before anything is compiled), edits land in the future.
    """
    path = project / 'scss' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    mtime = max(path.stat().st_mtime, now) + 2 if path.exists() else now - 100
    # written beside the file and renamed into place, so a reader never sees a half written source
    scratch = path.with_name(path.name + '.tmp')
    scratch.write_text(content)
    os.utime(scratch, (mtime, mtime))
    os.replace(scratch, path)
    return path


def output_of(project, name):
    return project / 'output' / 'css' / name


def test_finder_list_all(project):
    f = ScssFinder()
    for filename in CSS_NAMES:
        f._serve_static = True
        found = f.find(filename, find_all=True)
        assert isinstance(found, list)
        assert len(found) == 1
        assert str(found[0]).endswith(filename)

        f._serve_static = False
        found = f.find(filename, find_all=True)
        assert isinstance(found, list)
        assert len(found) == 0


def test_finder_find_not_all(project):
    f = ScssFinder()
    for filename in CSS_NAMES:
        f._serve_static = True
        found = f.find(filename)
        # returns the absolute path of the found file(s)
        assert isinstance(found, str)
        assert str(found).endswith(filename)

        f._serve_static = False
        found = f.find(filename)
        assert isinstance(found, list)
        assert not found


def test_finder_find_no_matching_paths_returns_empty_list(project):
    f = ScssFinder()
    for find_all in (True, False):
        found = f.find("nonexisting/path/to/somefile.css", find_all=find_all)
        assert not found
        assert found == []


def test_staticfiles_find_api(project):
    """The way django itself (runserver, findstatic) calls finders."""
    with override_settings(STATICFILES_FINDERS=['django_sass_finder.finders.ScssFinder']):
        finders.get_finder.cache_clear()
        try:
            found = finders.find('site.css')
            assert found and found.endswith('site.css')
            assert Path(found).read_text().strip()
            assert [Path(p).name for p in finders.find('site.css', find_all=True)] == ['site.css']
            assert finders.find('nope.css') is None
        finally:
            finders.get_finder.cache_clear()


def test_staticfiles_list_api(project):
    f = ScssFinder()
    listed = {path for path, storage in f.list([])}
    assert listed == set(CSS_NAMES)
    assert all(storage.location == str(project / 'output' / 'css') for _, storage in f.list([]))


def test_finder_find_recompiles_updated(project):
    f = ScssFinder()
    modified_times = {}
    for filename in CSS_NAMES:
        modified_times[filename] = Path(f.find(filename)).stat().st_mtime_ns

    time.sleep(0.05)
    # touch only the first one
    write_source(project, 'site.scss', FIXTURE_CONTENT['site.scss'])

    for filename in CSS_NAMES:
        changed = Path(f.find(filename)).stat().st_mtime_ns != modified_times[filename]
        assert changed == (filename == 'site.css'), filename


def test_finder_does_not_recompile_unchanged_in_new_process(project):
    """A fresh finder (a restarted server) reuses current output, thanks to the source map."""
    first = ScssFinder()
    mtimes = {name: Path(first.find(name)).stat().st_mtime_ns for name in CSS_NAMES}
    time.sleep(0.05)
    second = ScssFinder()
    for name in CSS_NAMES:
        assert Path(second.find(name)).stat().st_mtime_ns == mtimes[name]


def test_finder_recompiles_when_imported_partial_changes(project):
    write_source(project, '_vars.scss', '$colour: red;\n')
    write_source(project, 'themed.scss', '@import "vars";\na { color: $colour; }\n')
    f = ScssFinder()
    css = Path(f.find('themed.css'))
    assert 'red' in css.read_text()

    write_source(project, '_vars.scss', '$colour: blue;\n')
    assert 'blue' in Path(f.find('themed.css')).read_text()


def test_finder_notices_changed_partial_after_restart(project):
    write_source(project, '_vars.scss', '$colour: red;\n')
    write_source(project, 'themed.scss', '@import "vars";\na { color: $colour; }\n')
    assert 'red' in Path(ScssFinder().find('themed.css')).read_text()

    write_source(project, '_vars.scss', '$colour: blue;\n')
    assert 'blue' in Path(ScssFinder().find('themed.css')).read_text()


def test_finder_does_not_compile_partials_on_their_own(project):
    write_source(project, '_vars.scss', '$colour: red;\n')
    f = ScssFinder()
    assert f.find('_vars.css') == []
    assert not any(name.startswith('_') for name, _ in f.list([]))
    assert not output_of(project, '_vars.css').exists()


def test_finder_include_paths(project):
    libs = project / 'node_modules'
    libs.mkdir()
    (libs / 'colours.scss').write_text('$brand: green;\n')
    write_source(project, 'branded.scss', '@import "colours";\na { color: $brand; }\n')
    assert 'green' in Path(ScssFinder().find('branded.css')).read_text()


def test_finder_writes_source_map_when_requested(project):
    f = ScssFinder()
    css = Path(f.find('site.css'))
    assert (css.parent / 'site.css.map').is_file()
    assert 'sourceMappingURL=site.css.map' in css.read_text()


def test_finder_leaves_no_source_map_when_not_requested(project):
    with override_settings(CSS_MAP=False):
        f = ScssFinder()
        css = Path(f.find('site.css'))
        assert not (css.parent / 'site.css.map').exists()
        assert 'sourceMappingURL' not in css.read_text()
        # without a map we cannot know what a file read, so a new process compiles again
        write_source(project, '_vars.scss', '$colour: red;\n')
        write_source(project, 'themed.scss', '@import "vars";\na { color: $colour; }\n')
        assert 'red' in Path(f.find('themed.css')).read_text()
        write_source(project, '_vars.scss', '$colour: blue;\n')
        assert 'blue' in Path(f.find('themed.css')).read_text()


def test_finder_removes_output_of_deleted_source(project):
    f = ScssFinder()
    css = Path(f.find('admin/admin-site.css'))
    assert css.is_file()
    (project / 'scss' / 'admin' / 'admin-site.scss').unlink()
    assert f.find('admin/admin-site.css') == []
    assert not css.exists()
    assert not (css.parent / 'admin-site.css.map').exists()


def test_finder_compile_error_is_raised_then_retried(project):
    path = write_source(project, 'broken.scss', 'a { color: ; ;;; { \n')
    f = ScssFinder()
    with pytest.raises(CompileError):
        f.find('site.css')
    write_source(project, 'broken.scss', 'a { color: red; }\n')
    assert 'red' in Path(f.find('broken.css')).read_text()
    assert path.exists()


def test_finder_overlapping_patterns_compile_once(project):
    with override_settings(SCSS_COMPILE=['site.scss', '**/*.scss']):
        f = ScssFinder()
        compiled = []
        real_compile = f.compiler.compile

        def counting_compile(source, *args, **kwargs):
            compiled.append(source.name)
            return real_compile(source, *args, **kwargs)
        f.compiler.compile = counting_compile
        assert sorted(name for name, _ in f.list([])) == sorted(CSS_NAMES)
        assert sorted(compiled) == sorted(Path(name).name for name in FIXTURE_CONTENT)


def test_finder_does_not_trust_a_dependency_changed_while_compiling(project):
    write_source(project, '_vars.scss', '$colour: red;\n')
    write_source(project, 'themed.scss', '@import "vars";\na { color: $colour; }\n')
    f = ScssFinder()
    assert 'red' in Path(f.find('themed.css')).read_text()

    real_compile = f.compiler.compile
    edits = []

    def compile_and_edit(source, *args, **kwargs):
        result = real_compile(source, *args, **kwargs)
        if source.name == 'themed.scss' and not edits:
            # the dependency is edited after the compiler read it, before the finder looked
            edits.append(write_source(project, '_vars.scss', '$colour: blue;\n'))
        return result

    write_source(project, 'themed.scss', '@import "vars";\na { color: $colour; } /* edit */\n')
    f.compiler.compile = compile_and_edit
    assert 'red' in Path(f.find('themed.css')).read_text()      # compiled from what was read
    assert edits
    f.compiler.compile = real_compile
    assert 'blue' in Path(f.find('themed.css')).read_text()     # but not trusted as current


def test_finder_rescan_interval(project):
    with override_settings(SCSS_RESCAN_INTERVAL=3600):
        f = ScssFinder()
        assert f.find('site.css')
        write_source(project, 'late.scss', 'a { b: c }\n')
        assert f.find('late.css') == []         # within the interval: not scanned again
        f._last_scan -= 7200
        assert f.find('late.css')


def test_finder_is_threadsafe(project):
    f = ScssFinder()
    stop = threading.Event()

    def churn():
        n = 0
        while not stop.is_set():
            n += 1
            write_source(project, 'site.scss', FIXTURE_CONTENT['site.scss'] + f'/* {n} */\n')
            time.sleep(0.01)

    def lookup(_):
        return [bool(f.find(name)) for name in CSS_NAMES]

    thread = threading.Thread(target=churn)
    thread.start()
    try:
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lookup, range(40)))
    finally:
        stop.set()
        thread.join()
    assert all(all(row) for row in results)


def test_check_reports_unsupported_style(project):
    with override_settings(CSS_STYLE='no-such-style'):
        assert 'sass.E003' in [e.id for e in ScssFinder().check()]
    assert ScssFinder().check() == []


def test_check_reports_pattern_without_files(project):
    with override_settings(SCSS_COMPILE=['nothing-here.scss']):
        assert [e.id for e in ScssFinder().check()] == ['sass.E001']


def test_check_reports_pattern_matching_only_partials(project):
    write_source(project, '_only.scss', '$a: 1;\n')
    with override_settings(SCSS_COMPILE=['_only.scss']):
        errors = ScssFinder().check()
        assert [e.id for e in errors] == ['sass.E001']
        assert 'partials' in errors[0].msg
    with override_settings(SCSS_COMPILE=['*.scss']):
        assert ScssFinder().check() == []       # a pattern that also matches real sources is fine


@pytest.mark.parametrize('compiler', [
    'no.such.module.Compiler',      # missing module
    'django_sass_finder.compilers.Nope',     # missing class
    'nodots',                       # not a dotted path
    'django_sass_finder.finders.logger',     # not a class
])
def test_check_reports_unloadable_compiler(project, compiler):
    with override_settings(SCSS_COMPILER=compiler):
        finder = ScssFinder()
        assert [e.id for e in finder.check() if e.id == 'sass.E004'] == ['sass.E004']
        with pytest.raises(ImproperlyConfigured):
            finder.find('site.css')


def test_check_reports_compiler_rejecting_its_options(project):
    with override_settings(SCSS_COMPILER='django_sass_finder.compilers.libsass.LibsassCompiler',
                           SCSS_EXECUTABLE='/some/sass'):
        assert 'sass.E004' in [e.id for e in ScssFinder().check()]      # libsass takes no executable


def test_check_reports_missing_dart_executable(project):
    with override_settings(SCSS_COMPILER='dart', SCSS_EXECUTABLE='/no/such/sass'):
        assert 'sass.E002' in [e.id for e in ScssFinder().check()]


def test_dart_compressed_style_and_modules():
    """Modern Sass: only Dart Sass understands the module system."""
    if get_compiler('dart').check():
        pytest.skip('dart compiler unavailable')
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        (base / 'scss').mkdir()
        (base / 'scss' / '_vars.scss').write_text('$c: #333;\n')
        (base / 'scss' / 'site.scss').write_text(
            '@use "sass:color";\n@use "vars";\na { color: vars.$c; b: color.scale(vars.$c, $lightness: 20%); }\n')
        with override_settings(SCSS_COMPILER='dart', SCSS_ROOT=base / 'scss', CSS_COMPILE_DIR=base / 'css',
                               CSS_STYLE='compressed', CSS_MAP=True, SCSS_RESCAN_INTERVAL=0):
            css = Path(ScssFinder().find('site.css'))
            text = css.read_text()
            assert text.startswith('a{color:#333;')
            # the module is tracked as a dependency too
            (base / 'scss' / '_vars.scss').write_text('$c: #444;\n')
            os.utime(base / 'scss' / '_vars.scss', (time.time() + 10, time.time() + 10))
            assert Path(ScssFinder().find('site.css')).read_text().startswith('a{color:#444;')
