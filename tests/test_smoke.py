"""Import / bytecode smoke checks (no network)."""

from __future__ import annotations

import compileall
from pathlib import Path


def test_import_every_module():
    import app.config
    import app.control
    import app.core.engine
    import app.core.orders
    import app.core.poller
    import app.core.portfolio
    import app.core.schema
    import app.core.trader
    import app.events
    import app.main
    import app.notifications.telegram
    import app.perps.account
    import app.perps.client
    import app.perps.engine
    import app.perps.schema
    import app.perps.trader
    import app.pm.clob
    import app.runtime
    import app.session
    import app.settings
    import app.stats
    import app.storage.history
    import app.targets
    import app.utils.keyed_lock
    import app.web.server

    assert hasattr(app.main, "amain")
    assert hasattr(app.config, "validate_config")
    assert hasattr(app.web.server, "DashboardServer")
    assert hasattr(app.perps.engine, "PerpsEngine")


def test_compileall_app():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    assert compileall.compile_dir(str(app_dir), force=True, quiet=1)
