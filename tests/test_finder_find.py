# -*- coding: utf-8 -*-
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from django.test.utils import override_settings

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


@pytest.fixture(scope='session')
def basedir():

    with TemporaryDirectory() as tmppath:
        tmpdir = Path(tmppath).resolve(strict=True)
        base_dir = tmpdir
        staticfiles_dir = base_dir / 'static'
        scss_root = base_dir / 'scss'
        scss_compile = ['**/*.scss']
        # use a separate storage for our files (not staticfiles or appdirs)
        css_compile_dir_default = base_dir / 'output' / 'css'
        static_root = base_dir / 'static_root'
        for filename, scss_content in FIXTURE_CONTENT.items():
            scss_file: Path = scss_root / filename
            scss_file.parent.mkdir(parents=True, exist_ok=True)
            scss_file.write_text(scss_content)
        with override_settings(
                SCSS_ROOT=scss_root,
                SCSS_COMPILE=scss_compile,
                SCSS_INCLUDE_PATHS=[base_dir / 'node_modules'],
                CSS_COMPILE_DIR=css_compile_dir_default,
                STATICFILES_DIRS=[staticfiles_dir],
                CSS_STYLE='compact',
                CSS_MAP=True,
                STATIC_ROOT=static_root):
            yield tmpdir


def test_finder_list_all(basedir):
    f = ScssFinder()
    for filename in FIXTURE_CONTENT.keys():
        # change ext to .css
        filename = filename.rsplit('.', maxsplit=1)[0] + '.css'

        f._serve_static = True
        found = f.find(filename, all=True)
        assert isinstance(found, list)
        assert len(found) == 1
        assert str(found[0]).endswith(filename)

        f._serve_static = False
        found = f.find(filename, all=True)
        assert isinstance(found, list)
        assert len(found) == 0


def test_finder_find_not_all(basedir):
    f = ScssFinder()
    for filename in FIXTURE_CONTENT.keys():
        # change ext to .css
        filename = filename.rsplit('.', maxsplit=1)[0] + '.css'

        f._serve_static = True
        found = f.find(filename, all=False)
        # returns the absolute path of the found file(s)
        assert isinstance(found, str)
        assert str(found).endswith(filename)

        f._serve_static = False
        found = f.find(filename, all=False)
        # returns the absolute path of the found file(s)
        assert isinstance(found, list)
        assert not found


def test_finder_find_all_no_matching_paths_returns_empty_list(basedir):
    f = ScssFinder()
    found = f.find("nonexisting/path/to/somefile.css", all=True)
    assert not found
    assert found == []


def test_finder_find_no_matching_paths_returns_empty_list(basedir):
    f = ScssFinder()
    found = f.find("nonexisting/path/to/somefile.css", all=False)
    assert not found
    assert found == []


def test_finder_find_recompiles_updated(basedir):
    f = ScssFinder()

    # -- fixture generation --
    modified_times = {}
    # scan first, and save modified times of output files
    for filename in FIXTURE_CONTENT.keys():
        # change ext to .css
        filename = filename.rsplit('.', maxsplit=1)[0] + '.css'
        # use find to kick off a scss_compile
        for found_file in f.find(filename, all=True):
            found_path = Path(found_file)
            modified_times[found_path] = found_path.stat().st_mtime

    base_dir = basedir
    scss_root = base_dir / 'scss'

    def touch(name):
        filepath = scss_root / name
        filepath.touch(exist_ok=True)

    time.sleep(0.5)
    for filename in FIXTURE_CONTENT.keys():
        # touch only the first one
        touch(filename)
        break

    first = True
    # iterate
    for filename in FIXTURE_CONTENT.keys():
        # change ext to .css
        filename = filename.rsplit('.', maxsplit=1)[0] + '.css'
        # use find to kick off a scss_compile
        for found_file in f.find(filename, all=True):
            found_path = Path(found_file)
            if first:
                assert modified_times[found_path] != found_path.stat().st_mtime
                first = False
            else:
                assert modified_times[found_path] == found_path.stat().st_mtime

    # double-check we did at least one iteration
    assert not first
