import argparse
import importlib
import json
import sys
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from uuid import uuid4

import gifnoc
import uvicorn
from authlib.integrations.starlette_client import OAuth
from gifnoc import Command, Option
from hrepr import H
from starbear.serve import debug_mode, dev_injections
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import OAuthMiddleware, PermissionDict, PermissionFile
from .config import config as gzconfig
from .find import collect_routes, collect_routes_from_module, compile_routes
from .reload import FullReloader, InertReloader, JuriggedReloader
from .utils import UsageError


class Grizzlaxy:
    def __init__(self, config):
        root = config.root
        module = config.module
        port = config.port
        host = config.host
        ssl = config.ssl
        oauth = config.oauth
        watch = config.watch
        dev = config.dev
        reload_mode = config.reload_mode
        sentry = config.sentry

        if dev and not watch:
            watch = True
        if watch:
            dev = True

        if not dev:
            self.reloader = InertReloader(self)
        elif reload_mode == "jurigged":
            self.reloader = JuriggedReloader(self)
        else:
            self.reloader = FullReloader(self)

        if not ((root is None) ^ (module is None)):
            # xor requires exactly one of the two to be given
            raise UsageError("Either the root or module argument must be provided.")

        self.reloader.prep()

        if isinstance(module, str):
            module = importlib.import_module(module)

        if watch is True:
            if module is not None:
                watch = Path(module.__file__).parent
            else:
                watch = root

        self.reloader.code_watch(watch, module)

        self.root = root
        self.module = module
        self.port = port
        self.host = host
        self.ssl = ssl
        self.oauth = oauth
        self.watch = watch
        self.dev = dev
        self.reload_mode = reload_mode
        self.sentry = sentry

        self.setup()

    def setup(self):
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
        self.set_routes()

    def set_routes(self):
        if self.root:
            collected = collect_routes(self.root)
        elif self.module:
            collected = collect_routes_from_module(self.module)

        routes = compile_routes("/", collected)
        self.reloader.inject_routes(routes)

        for route in routes:
            route._grizzlaxy_managed = True

        remainder = [
            r for r in self.app.router.routes if not getattr(r, "_grizzlaxy_managed", False)
        ]
        self.app.router.routes = routes + remainder
        self.app.map = collected

    def run(self):
        token = debug_mode.set(self.dev)
        try:
            uvicorn.run(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info",
                ssl_keyfile=self.ssl_keyfile,
                ssl_certfile=self.ssl_certfile,
            )
        finally:
            debug_mode.reset(token)


def grizzlaxy(config=None, **kwargs):
    if config is None:
        config = GrizzlaxyConfig(**kwargs)
    gz = Grizzlaxy(config)
    gz.run()


def main(argv=None):
    with gifnoc.cli(
        argparser=argparse.ArgumentParser(description="Start a grizzlaxy of starbears."),
        options=Command(
            mount="grizzlaxy",
            options={
                ".root": "--root",
                ".module": Option(aliases=["-m"]),
                ".port": Option(aliases=["-p"]),
                ".host": "--host",
                ".oauth.permissions": "--permissions",
                ".ssl.keyfile": "--ssl-keyfile",
                ".ssl.certfile": "--ssl-certfile",
                ".dev": "--dev",
                ".reload_mode": "--reload-mode",
                ".watch": "--watch",
            },
        ),
        argv=sys.argv[1:] if argv is None else argv,
    ):
        try:
            grizzlaxy(gzconfig)
        except UsageError as exc:
            exit(f"ERROR: {exc}")
        except FileNotFoundError as exc:
            exit(f"ERROR: File not found: {exc}")
