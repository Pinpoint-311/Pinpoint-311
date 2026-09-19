"""No test module may leave a fake in `sys.modules`.

This exists because of a specific, expensive failure. `test_secret_manager.py`
wrote three `types.ModuleType` fakes into `sys.modules` at import time --
`app.core.sanitize`, `app.db.session`, `app.services.api_usage` -- and never
removed them. Whichever module collected next got the fakes. `app.main` imports
`get_usage_summary` from `app.services.api_usage`; the fake had one attribute,
so `test_security_headers.py` raised

    ImportError: cannot import name 'get_usage_summary' from 'app.services.api_usage'

*at collection*. A collection error is fatal to the run: `pytest tests -q`
reported one error and executed zero tests. Nothing in the suite was running,
and the traceback pointed at `app.main`, which was fine.

The check below is behavioural, not textual: it looks at the actual
`sys.modules` this process is carrying by the time it runs. A stub installed
and restored per test (`monkeypatch.setitem`, which `test_kms_azure.py` and
`test_provider_dispatch.py` use correctly) is invisible here. A stub written in
at import time is not.

Placed in a file whose name sorts after `test_secret_manager.py` so it collects
and runs afterwards, which is the ordering that made the original bug bite.
"""

import sys
import types

import pytest

# The one documented exception. `conftest.py` substitutes a minimal
# `app.core.config` *only* when the real one cannot be imported (no
# pydantic-settings in CI's environment), and the whole suite depends on that
# fallback. It is a bootstrap, not a per-test convenience.
ALLOWED_STUBS = {"app.core.config"}


def _leaked_stubs() -> dict:
    """`app.*` entries in sys.modules that are not real, file-backed modules."""
    leaked = {}
    for name, module in list(sys.modules.items()):
        if not name.startswith("app.") and name != "app":
            continue
        if name in ALLOWED_STUBS or module is None:
            continue
        # A real module has a __file__; a namespace package has a __path__.
        # A `types.ModuleType(...)` handed a few attributes has neither.
        if getattr(module, "__file__", None) or getattr(module, "__path__", None):
            continue
        leaked[name] = module
    return leaked


def test_no_test_module_has_replaced_an_app_module_globally():
    leaked = _leaked_stubs()
    assert not leaked, (
        "these app modules have been replaced by in-memory fakes that outlived "
        f"the test that installed them: {sorted(leaked)}. Every module importing "
        "one of them for the rest of this run gets the fake -- which is how the "
        "whole suite once aborted at collection and ran zero tests. Install "
        "stubs with `monkeypatch.setitem(sys.modules, ...)` inside a fixture so "
        "they are removed again."
    )


def test_the_real_api_usage_module_is_importable():
    """The exact import `app.main` performs, and the exact one the leaked fake
    broke. Kept separate so the failure names the symbol, not just the module."""
    api_usage = pytest.importorskip("app.services.api_usage")

    assert not isinstance(api_usage, types.ModuleType) or getattr(
        api_usage, "__file__", None
    ), "app.services.api_usage is a stub, not the real module"
    assert hasattr(api_usage, "get_usage_summary"), (
        "app.services.api_usage has no get_usage_summary -- app.main imports it "
        "by name and will fail at collection for every module that imports app.main"
    )
