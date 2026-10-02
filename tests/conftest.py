"""Root test configuration.

Unit tests need no database. Integration tests (tests/integration) run against
a *disposable* Postgres database named by TEST_POSTGRES_DB - it is dropped and
recreated on every run, so it must end in "_test". The override has to happen
here, before any test module imports `app.core.config` (settings are built once
at import time).
"""

import os

TEST_DB = os.environ.get("TEST_POSTGRES_DB")
if TEST_DB:
    if not TEST_DB.endswith("_test"):
        raise RuntimeError("TEST_POSTGRES_DB must end with '_test' - it is dropped and recreated on every run")
    os.environ["POSTGRES_DB"] = TEST_DB
