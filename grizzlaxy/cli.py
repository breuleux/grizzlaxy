import argparse
import asyncio
import importlib
import json
import sys
from asyncio import Future
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from authlib.integrations.starlette_client import OAuth
from hrepr import H
from sse_starlette.sse import EventSourceResponse
from starbear.serve import dev_injections
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from .auth import OAuthMiddleware, PermissionDict, PermissionFile
from .find import collect_routes, collect_routes_from_module, compile_routes
from .utils import UsageError, merge, read_configs


class JuriggedLooper:
    def __init__(self, watcher):
        self.future = None
        self.watcher = watcher
        self.watcher.activity.append(self.handle)

    def handle(self):
        if self.future and not self.future.done():
            self.future.set_result(True)

    async def __aiter__(self):
        try:
            while True:
                self.future = Future()
                await self.future
                await asyncio.sleep(0.05)
                yield True
        except asyncio.CancelledError:
            self.watcher.activity.remove(self.handle)


class Watcher:
    def __init__(self, watch, registry, towatch):
        from watchdog.observers import Observer

        self.watch = watch
        self.registry = registry
        self.towatch = towatch
        self.activity = []

        self.registry.activity.register(self.handle_jurigged)
        self.obs = Observer()
        self.obs.schedule(self, self.watch, recursive=True)
        self.obs.start()

    def fire(self):
        for listener in self.activity:
            listener()

    def handle_jurigged(self, event):
        if isinstance(event, self.towatch):
            self.fire()

    def dispatch(self, event):
        if not event.src_path.endswith(".py"):
            self.fire()


class Grizzlaxy:
    def __init__(
        self,
        root=None,
        module=None,
        port=None,
        host=None,
        ssl=None,
        oauth=None,
        watch=False,
        sentry=None,
        config={},
    ):
        if not ((root is None) ^ (module is None)):
            # xor requires exactly one of the two to be given
            raise UsageError("Either the root or module argument must be provided.")

        if watch:
            # Sometimes has to be done before importing the module to watch in order
            # to properly collect function data
            import codefind  # noqa: F401

        if isinstance(module, str):
            module = importlib.import_module(module)

        if watch:
            import jurigged

            if watch is True:
                if module is not None:
                    watch = Path(module.__file__).parent
                else:
                    watch = root

            jurigged.watch(str(watch))

        self.root = root
        self.module = module
        self.port = port
        self.host = host
        self.ssl = ssl
        self.oauth = oauth
        self.watch = watch
        self.sentry = sentry
        self.config = config

        self.setup()

    def setup(self):
        if self.watch:
            self.inject_reloading_code()

        app = Starlette(routes=[])

        def _ensure(filename, enabled):
            if not enabled or not filename:
                return None
            if not Path(filename).exists():
                raise FileNotFoundError(filename)
            return filename

        ssl_enabled = self.ssl.get("enabled", True)
        self.ssl_keyfile = _ensure(self.ssl.get("keyfile", None), ssl_enabled)
        self.ssl_certfile = _ensure(self.ssl.get("certfile", None), ssl_enabled)

        if ssl_enabled and self.ssl_certfile and self.ssl_keyfile:
            # This doesn't seem to do anything?
            app.add_middleware(HTTPSRedirectMiddleware)

        if self.oauth and self.oauth.get("enabled", True):
            permissions = self.oauth.get("permissions", None)
            if permissions:
                if isinstance(permissions, str):
                    permissions = Path(permissions)
                if isinstance(permissions, Path):
                    try:
                        permissions = PermissionFile(permissions)
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

            oauth_config = Config(
                environ=self.oauth.get("environ", {}),
                env_file=self.oauth.get("secrets_file", None),
            )
            oauth_module = OAuth(oauth_config)
            oauth_module.register(
                name=self.oauth["name"],
                server_metadata_url=self.oauth["server_metadata_url"],
                client_kwargs=self.oauth["client_kwargs"],
            )
            app.add_middleware(
                OAuthMiddleware,
                oauth=oauth_module,
                is_authorized=permissions,
            )
            app.add_middleware(SessionMiddleware, secret_key=uuid4().hex)
        else:
            permissions = None

        if self.sentry and self.sentry.get("enabled", True):
            import logging
            import sentry_sdk
            # Configure sentry to collect log events with minimal level INFO
            # (2023/10/25) https://docs.sentry.io/platforms/python/integrations/logging/
            from sentry_sdk.integrations.logging import LoggingIntegration

            def _get_level(level_name: str) -> int:
                level = logging.getLevelName(level_name)
                return level if isinstance(level, int) else logging.INFO

            sentry_sdk.init(
                dsn=self.sentry.get("dsn", None),
                traces_sample_rate=self.sentry.get("traces_sample_rate", None),
                environment=self.sentry.get("environment", None),
                integrations=[
                    LoggingIntegration(
                        level=_get_level(self.sentry.get("log_level", "")),
                        event_level=_get_level(self.sentry.get("event_log_level", ""))
                    )
                ]
            )

        app.grizzlaxy = SimpleNamespace(
            permissions=permissions,
        )

        self.app = app
        self.set_routes()

    def inject_reloading_code(self):
        dev_injections.append(
            H.script(
                """
                let src = new EventSource("/!!events");
                src.onmessage = e => {
                    window.location.reload();
                }
                """
            )
        )
        self.watcher.activity.append(self.set_routes)

    @cached_property
    def watcher(self):
        from jurigged.codetools import CodeFileOperation
        from jurigged.register import registry

        return Watcher(self.watch, registry, CodeFileOperation)

    async def event_source(self, request):
        return EventSourceResponse(JuriggedLooper(self.watcher))

    def set_routes(self):
        if self.root:
            collected = collect_routes(self.root)
        elif self.module:
            collected = collect_routes_from_module(self.module)

        routes = compile_routes("/", self.config, collected)
        if self.watch:
            routes.insert(0, Route("/!!events", self.event_source))

        self.app.router.routes = routes
        self.app.map = collected

    def run(self):
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            ssl_keyfile=self.ssl_keyfile,
            ssl_certfile=self.ssl_certfile,
        )


def grizzlaxy(
    root=None,
    module=None,
    port=None,
    host=None,
    ssl=None,
    oauth=None,
    watch=False,
    sentry=None,
    config={},
):
    gz = Grizzlaxy(
        root=root,
        module=module,
        port=port,
        host=host,
        ssl=ssl,
        oauth=oauth,
        watch=watch,
        sentry=sentry,
        config=config,
    )
    gz.run()


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description="Start a grizzlaxy of starbears.")

    parser.add_argument(
        "root", nargs="?", metavar="ROOT", help="Directory or script", default=None
    )
    parser.add_argument(
        "--module", "-m", metavar="MODULE", help="Directory or script", default=None
    )
    parser.add_argument(
        "--config",
        "-C",
        metavar="CONFIG",
        action="append",
        help="Configuration file(s)",
        default=None,
    )
    parser.add_argument("--port", type=int, help="Port to serve on", default=None)
    parser.add_argument("--host", type=str, help="Hostname", default=None)
    parser.add_argument(
        "--permissions", type=str, help="Permissions file", default=None
    )
    parser.add_argument("--secrets", type=str, help="Secrets file", default=None)
    parser.add_argument("--ssl-keyfile", type=str, help="SSL key file", default=None)
    parser.add_argument(
        "--ssl-certfile", type=str, help="SSL certificate file", default=None
    )
    parser.add_argument(
        "--hot",
        action=argparse.BooleanOptionalAction,
        help="Automatically hot-reload the code",
    )
    parser.add_argument(
        "--watch",
        type=str,
        help="Path to watch for changes with jurigged",
    )

    options = parser.parse_args(argv[1:])

    ##############################
    # Populate the configuration #
    ##############################

    config = {
        "grizzlaxy": {
            "root": None,
            "module": None,
            "port": 8000,
            "host": "127.0.0.1",
            "ssl": {},
            "oauth": {},
            "sentry": {},
            "watch": None,
        }
    }

    if options.config:
        config = merge(config, read_configs(*options.config))

    gconfig = config["grizzlaxy"]

    for field in ("root", "module", "port", "host", "watch"):
        value = getattr(options, field)
        if value is not None:
            gconfig[field] = value

    if options.hot and not config["watch"]:
        gconfig["watch"] = True
    if options.hot is False:
        gconfig["watch"] = None

    # TODO: remove this option
    if options.secrets:
        gconfig["oauth"] = {
            "name": "google",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            "client_kwargs": {
                "scope": "openid email profile",
                "prompt": "select_account",
            },
            "secrets_file": options.secrets,
        }
    if options.permissions:
        gconfig["oauth"]["permissions"] = options.permissions

    if options.ssl_keyfile:
        gconfig["ssl"]["keyfile"] = options.ssl_keyfile
    if options.ssl_certfile:
        gconfig["ssl"]["certfile"] = options.ssl_certfile

    #################
    # Run grizzlaxy #
    #################

    try:
        del config["grizzlaxy"]
        grizzlaxy(**gconfig, config=config)
    except UsageError as exc:
        exit(f"ERROR: {exc}")
    except FileNotFoundError as exc:
        exit(f"ERROR: File not found: {exc}")
