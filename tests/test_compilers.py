# -*- coding: utf-8 -*-
import json
import logging
import sys
from pathlib import Path

import pytest

from django.test.utils import override_settings

from django_sass_finder.compilers import read_map_sources
from django_sass_finder.compilers.libsass import LibsassCompiler
from django_sass_finder.finders import ScssFinder


def write_map(path: Path, content) -> Path:
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


class TestReadMapSources:
    def test_reads_relative_sources(self, tmp_path):
        mapfile = write_map(tmp_path / 'a.css.map', {'sources': ['a.scss', 'sub/_b.scss']})
        assert read_map_sources(mapfile) == {tmp_path / 'a.scss', tmp_path / 'sub' / '_b.scss'}

    @pytest.mark.parametrize('content', [
        '{not json',
        '[]',
        {'version': 3},
        {'sources': None},
        {'sources': 'a.scss'},
        {'sources': {'a': 'b'}},
        {'sources': [1]},
        {'sources': ['a.scss', None]},
    ])
    def test_unusable_map_is_none(self, tmp_path, content):
        assert read_map_sources(write_map(tmp_path / 'a.css.map', content)) is None

    def test_missing_map_is_none(self, tmp_path):
        assert read_map_sources(tmp_path / 'nothing.css.map') is None


def test_libsass_hint_names_this_distribution(monkeypatch):
    monkeypatch.setitem(sys.modules, 'sass', None)      # makes `import sass` fail
    (error,) = LibsassCompiler().check()
    assert 'django-dart-sass-finder[libsass]' in error.msg
    assert 'pip install "django-sass-finder' not in error.msg


def test_failure_to_remove_a_stale_output_is_logged_not_retried(tmp_path, caplog, monkeypatch):
    root = tmp_path / 'scss'
    root.mkdir()
    (root / 'site.scss').write_text('a { b: c }\n')
    with override_settings(SCSS_ROOT=root, SCSS_COMPILE=['**/*.scss'], CSS_COMPILE_DIR=tmp_path / 'css',
                           SCSS_RESCAN_INTERVAL=0, SCSS_COMPILER='dart', CSS_MAP=True):
        finder = ScssFinder()
        if finder.compiler.check():
            pytest.skip('dart compiler unavailable')
        assert finder.find('site.css')
        (root / 'site.scss').unlink()

        def refuse(self, missing_ok=False):
            raise PermissionError('read-only')
        monkeypatch.setattr(Path, 'unlink', refuse)
        with caplog.at_level(logging.WARNING, logger='django_sass_finder.finders'):
            assert finder.find('site.css') == []
        assert 'Could not remove' in caplog.text and 'read-only' in caplog.text
        assert not finder.source_cache      # forgotten, not retried
