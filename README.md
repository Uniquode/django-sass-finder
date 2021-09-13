# django_sass_finder
a Django finder that compiles Sass files

## installation
### WARNING: MAKE SURE YOU HAVE NO SASS PACKAGES INSTALLED (other than libsass)!
run `pip install django_sass_finder` to add this module to your virtualenv,
then add the finder to the list your static file finders as follows:

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

The following additional (with examples) settings are used and required by this staticfiles finder:

```python
BASE_DIR = ...

SCSS_ROOT = BASE_DIR / 'scss'   # where the .scss files are sourced
SCSS_COMPILE = [                # a list of filename pattern to search for within SCSS_ROOT
    'site.scss',                # default is **/*,css (all scss source files in and below SCSS_ROOT)                                                                                                                                                                                                                                                                                            
    'admin/admin.scss',
]
CSS_STYLE = 'compressed'            # optional: output format 'nested', 'expanded','compact','compressed'
CSS_MAP = True                      # optional: generate a source map
CSS_COMPILE_DIR = BASE_DIR / 'static' / 'css'   # The target directories for the compiled .css
STATICFILES_ROOT = [                            # this should be at or above the CSS_COMPILE_DIR
    BASE_DIR / 'static'                         # but targetting {app}/static should also work
]
```

`BASE_DIR` and variants above are `pathlib.Path` objects, but path strings can also be used.


## usage
This module dynamically compiles to target .css files, and recompiles them on demand whenever
they are updated.

The `collectstatic` management command compiles these, and lets the `FilesystemFinder` transfer
them to STATIC_ROOT. The development server is perfectly able to serve these from
STATICFILES_ROOT without the need to `collectstatic`.

## license
this package is licensed under the MIT license.
