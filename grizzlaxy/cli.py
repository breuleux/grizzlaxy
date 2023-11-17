import argparse
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from authlib.integrations.starlette_client import OAuth
from starlette.applications import Starlette
from starlette.config import Config
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .auth import OAuthMiddleware, PermissionDict, PermissionFile
from .find import collect_routes, collect_routes_from_module, compile_routes
from .utils import UsageError, read_config


def grizzlaxy(
    root=None,
    module=None,
    port=None,
    host=None,
    permissions=None,
    ssl=None,
    oauth=None,
    watch=False,
    relative_to=None,
):
    relative_to = Path(relative_to)

    if not ((root is None) ^ (module is None)):
        # xor requires exactly one of the two to be given
        raise UsageError("Either the root or module argument must be provided.")

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

    if root:
        collected = collect_routes(root)
    elif module:
        collected = collect_routes_from_module(module)

    routes = compile_routes("/", collected)

    app = Starlette(routes=routes)

    if ssl:
        # This doesn't seem to do anything?
        app.add_middleware(HTTPSRedirectMiddleware)

    if oauth:
        if permissions:
            if isinstance(permissions, str):
                permissions = Path(permissions)
            if isinstance(permissions, Path):
                try:
                    permissions = PermissionFile(relative_to / permissions)
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
            permissions = PermissionDict({})

        oauth_config = Config(
            environ=oauth.get("environ", {}),
            env_file=oauth.get("secrets_file", None),
        )
        oauth_module = OAuth(oauth_config)
        oauth_module.register(
            name=oauth["name"],
            server_metadata_url=oauth["server_metadata_url"],
            client_kwargs=oauth["client_kwargs"],
        )
        app.add_middleware(
            OAuthMiddleware,
            oauth=oauth_module,
            is_authorized=permissions,
        )
        app.add_middleware(SessionMiddleware, secret_key=uuid4().hex)
    else:
        permissions = None

    app.map = collected
    app.grizzlaxy = SimpleNamespace(
        permissions=permissions,
    )

    ssl = ssl or {}
    ssl_keyfile = ssl.get("keyfile", None)
    ssl_certfile = ssl.get("certfile", None)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        ssl_keyfile=ssl_keyfile and relative_to / ssl_keyfile,
        ssl_certfile=ssl_certfile and relative_to / ssl_certfile,
    )


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
        "--config", "-C", metavar="CONFIG", help="Configuration file", default=None
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
        "root": None,
        "module": None,
        "port": 8000,
        "host": "127.0.0.1",
        "permissions": None,
        "ssl": {},
        "oauth": {},
        "watch": None,
        "relative_to": Path.cwd(),
    }

    if options.config:
        config_file = Path(options.config)
        content = read_config(config_file)
        if "grizzlaxy" in content:
            content = content["grizzlaxy"]
        config.update(content)
        config["relative_to"] = config_file.parent

    for field in ("root", "module", "port", "host", "watch", "permissions"):
        value = getattr(options, field)
        if value is not None:
            config[field] = value

    if options.hot and not config["watch"]:
        config["watch"] = True
    if options.hot is False:
        config["watch"] = None

    # TODO: remove this option
    if options.secrets:
        config["oauth"] = {
            "name": "google",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            "client_kwargs": {
                "scope": "openid email profile",
                "prompt": "select_account",
            },
            "secrets_file": options.secrets,
        }

    if options.ssl_keyfile:
        config["ssl"]["keyfile"] = options.ssl_keyfile
    if options.ssl_certfile:
        config["ssl"]["certfile"] = options.ssl_certfile

    #################
    # Run grizzlaxy #
    #################

    try:
        grizzlaxy(**config)
    except UsageError as exc:
        exit(f"ERROR: {exc}")
    except FileNotFoundError as exc:
        exit(f"ERROR: File not found: {exc}")
