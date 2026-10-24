"""Test fixtures. SWIPE_DATA must point at a temp dir BEFORE app.py is
imported — app.py resolves DATA_DIR at import time."""

import os
import shutil
import sys
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="swipe-test-")
os.environ["SWIPE_DATA"] = _TMPDIR

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest  # noqa: E402

import app as swipe  # noqa: E402


@pytest.fixture()
def client():
    shutil.rmtree(swipe.DATA_DIR, ignore_errors=True)
    os.makedirs(swipe.DATA_DIR)
    swipe.app.config["TESTING"] = True
    with swipe.app.test_client() as c:
        yield c
