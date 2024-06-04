import errno
import importlib
import ipaddress
import json
import os
import random
import socket
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import uvicorn
from authlib.integrations.starlette_client import OAuth
from hrepr import H
from starbear.serve import debug_mode, dev_injections
from starbear.utils import logger
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import OAuthMiddleware, PermissionDict, PermissionFile
from .find import collect_locations, collect_routes, collect_routes_from_module, compile_routes
from .reload import FullReloader, InertReloader, JuriggedReloader
from .utils import UsageError


class ThreadedServer(uvicorn.Server):
    def install_signal_handlers(self):
        pass

    def run(self):
        thread = threading.Thread(target=super().run)
        thread.start()


@dataclass
class GrizzlaxySSLConfig:
    # Whether SSL is enabled
    enabled: bool = False
    # SSL key file
    keyfile: Path = None
    # SSL certificate file
    certfile: Path = None


@dataclass
class GrizzlaxyOAuthConfig:
    # Whether OAuth is enabled
    enabled: bool = False
    # Permissions file
    permissions: Path = None
    default_permissions: dict = None
    name: str = None
    server_metadata_url: str = None
    client_kwargs: dict = field(default_factory=dict)
    environ: dict = field(default_factory=dict)


@dataclass
class GrizzlaxySentryConfig:
    # Whether Sentry is enabled
    enabled: bool = False
    dsn: str = None
    traces_sample_rate: float = None
    environment: str = None
    log_level: str = None
    event_log_level: str = None


@dataclass
class GrizzlaxyBase:
    # Port to serve from
    port: int = 8000
    # Hostname to serve from
    host: str = "127.0.0.1"
    # Path to watch for changes with jurigged
    watch: str | bool = None
    # Run in development mode
    dev: bool = False
    # Automatically open browser
    open_browser: bool = False
    # Whether to use threads
    use_thread: bool = False
    # Reloading methodology
    reload_mode: str = "jurigged"
    # SSL configuration
    ssl: GrizzlaxySSLConfig = field(default_factory=GrizzlaxySSLConfig)
    # OAuth configuration
    oauth: GrizzlaxyOAuthConfig = field(default_factory=GrizzlaxyOAuthConfig)
    # Sentry configuration
    sentry: GrizzlaxySentryConfig = field(default_factory=GrizzlaxySentryConfig)

    def __post_init__(self):
        override = os.environ.get("GRIZZLAXY_RELOAD_OVERRIDE", None)
        if override:
            self.host, self.port = json.loads(override)
            self.open_browser = False

        if self.dev and not self.watch:
            self.watch = True
        if self.watch:
            self.dev = True

        if not self.dev:
            self.reloader = InertReloader(self)
        elif self.reload_mode == "jurigged":
            self.reloader = JuriggedReloader(self)
        else:
            self.reloader = FullReloader(self)

    @cached_property
    def socket(self):
        host = self.host
        if host == "127.255.255.255":
            # Generate a random loopback address (127.x.x.x)
            host = ipaddress.IPv4Address("127.0.0.1") + random.randrange(2**24 - 2)
            host = str(host)

        family = socket.AF_INET6 if ":" in host else socket.AF_INET

        sock = socket.socket(family=family)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind((host, self.port))
        except OSError as exc:
            if self.host == "127.255.255.255" and exc.errno == errno.EADDRNOTAVAIL:
                # The full 127.x.x.x range may not be available on this system
                sock.bind(("localhost", self.port))
            else:
                raise
        return sock

    def get_locations(self):
        return []

    def get_routes(self):
        if ((self.root is not None) + (self.module is not None) + (self.routes is not None)) != 1:
            raise UsageError(
                "Either the root or module argument must be provided, or a dict of explicit routes."
            )
        if self.root:
            collected = collect_routes(self.root)
        elif self.module:
            collected = collect_routes_from_module(self.module)
        elif self.routes:
            collected = self.routes
        return collected

    def inject_routes(self):
        collected = self.get_routes()
        routes = compile_routes("/", collected)
        self.reloader.inject_routes(routes)

        for route in routes:
            route._grizzlaxy_managed = True

        remainder = [
            r for r in self.app.router.routes if not getattr(r, "_grizzlaxy_managed", False)
        ]
        self.app.router.routes = routes + remainder
        self.app.map = collected

    def _setup(self):
        if self.watch is True:
            self.watch = self.get_locations()

        self.reloader.prep()
        self.reloader.code_watch(self.watch)

        code = self.reloader.browser_side_code()
        if code:
            dev_injections.append(
                H.script(
                    dedent(
                        f"""window.addEventListener("load", () => {{
                        {code}
                        }});
                        """
                    )
                )
            )

        app = Starlette(routes=[])

        @app.on_event("startup")
        async def _():
            protocol = "https" if self.ssl.enabled else "http"
            host, port = self.socket.getsockname()
            url = f"{protocol}://{host}:{port}"
            logger.info(f"Serving at: \x1b[1m{url}\x1b[0m")
            if self.open_browser:
                webbrowser.open(url)

        def _ensure(filename, enabled):
            if not enabled or not filename:
                return None
            if not Path(filename).exists():
                raise FileNotFoundError(filename)
            return filename

        ssl_enabled = self.ssl.enabled
        self.ssl_keyfile = _ensure(self.ssl.keyfile, ssl_enabled)
        self.ssl_certfile = _ensure(self.ssl.certfile, ssl_enabled)

        if ssl_enabled and self.ssl_certfile and self.ssl_keyfile:
            # This doesn't seem to do anything?
            app.add_middleware(HTTPSRedirectMiddleware)

        if self.oauth and self.oauth.enabled and self.oauth.name:
            permissions = self.oauth.permissions
            if permissions:
                if isinstance(permissions, str):
                    permissions = Path(permissions)
                if isinstance(permissions, Path):
                    try:
                        permissions = PermissionFile(
                            permissions, defaults=self.oauth.default_permissions
                        )
                    except json.JSONDecodeError as exc:
                        sys.exit(
                            f"ERROR decoding JSON: {exc}\n"
                            f"Please verify if file '{permissions}' contains valid JSON."
                        )
                elif isinstance(permissions, dict):
                    permissions = PermissionDict(permissions)
                else:
                    raise UsageError("permissions should be a path or dict")
            else:
                # Allow everyone everywhere (careful)
                def permissions(user, path):
                    return True

            oauth_config = Config(environ=self.oauth.environ)
            oauth_module = OAuth(oauth_config)
            oauth_module.register(
                name=self.oauth.name,
                server_metadata_url=self.oauth.server_metadata_url,
                client_kwargs=self.oauth.client_kwargs,
            )
            app.add_middleware(
                OAuthMiddleware,
                oauth=oauth_module,
                is_authorized=permissions,
            )
            app.add_middleware(SessionMiddleware, secret_key=uuid4().hex)
        else:
            permissions = None

        if self.sentry and self.sentry.enabled:
            import logging

            import sentry_sdk

            # Configure sentry to collect log events with minimal level INFO
            # (2023/10/25) https://docs.sentry.io/platforms/python/integrations/logging/
            from sentry_sdk.integrations.logging import LoggingIntegration

            def _get_level(level_name: str) -> int:
                level = logging.getLevelName(level_name)
                return level if isinstance(level, int) else logging.INFO

            sentry_sdk.init(
                dsn=self.sentry.dsn,
                traces_sample_rate=self.sentry.traces_sample_rate,
                environment=self.sentry.environment,
                integrations=[
                    LoggingIntegration(
                        level=_get_level(self.sentry.log_level or "ERROR"),
                        event_level=_get_level(self.sentry.event_log_level or "ERROR"),
                    )
                ],
            )

        app.grizzlaxy = SimpleNamespace(
            permissions=permissions,
        )

        self.app = app
        self.inject_routes()

    def run(self):
        self._setup()
        token = debug_mode.set(self.dev)
        uconfig = uvicorn.Config(
            app=self.app,
            fd=self.socket.fileno(),
            log_level="info",
            ssl_keyfile=self.ssl_keyfile,
            ssl_certfile=self.ssl_certfile,
        )
        server_class = ThreadedServer if self.use_thread else uvicorn.Server
        try:
            server_class(uconfig).run()
        finally:
            debug_mode.reset(token)


@dataclass
class Grizzlaxy(GrizzlaxyBase):
    # Directory or script
    root: str = None
    # Name of the module to run
    module: str | Any = None
    # Explicitly given routes
    routes: dict = None

    def get_locations(self):
        if self.root:
            locations = [self.root]

        elif self.module:
            if isinstance(self.module, str):
                self.module = importlib.import_module(self.module)
            locations = [Path(self.module.__file__).parent]

        elif self.routes:
            locations = list(collect_locations(self.routes))

        return [str(loc) for loc in locations]

    def get_routes(self):
        if ((self.root is not None) + (self.module is not None) + (self.routes is not None)) != 1:
            raise UsageError(
                "Either the root or module argument must be provided, or a dict of explicit routes."
            )

        if self.root:
            return collect_routes(self.root)

        elif self.module:
            if isinstance(self.module, str):
                self.module = importlib.import_module(self.module)
            return collect_routes_from_module(self.module)

        elif self.routes:
            return self.routes
