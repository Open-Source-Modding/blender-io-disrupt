"""Pytest fixtures for the blender-io-xbg addon.

Run under pytest-blender (re-executes pytest inside Blender's Python):
    pytest --blender-executable /usr/bin/blender
See pytest.ini for defaults.

The repo root is NOT added to sys.path here, to stop pytest from importing the
addon's root ``__init__.py`` as a package parent of ``tests/``.  Tests that need
the ``modules`` package import it lazily via ``tests.util.import_modules``.
"""
import os

import pytest

REPO_ROOT = os.environ.get("XBG_REPO_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)


@pytest.fixture(scope="session")
def wdl_dir():
    return os.environ.get(
        "XBG_WDL_DIR",
        "/home/selene/Documents/Modding/WDL/unpacked/common/graphics",
    )


@pytest.fixture(scope="session")
def wd1_dir():
    return os.environ.get(
        "XBG_WD1_DIR",
        "/home/selene/Documents/Modding/Watch Dogs/unpacked/windy_city/graphics",
    )
