import errno
import ipaddress
import json
import os
import random
import socket
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import gifnoc


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
class GrizzlaxyConfig:
    # Directory or script
    root: str = None
    # Name of the module to run
    module: str = None
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
    # Reloading methodology
    reload_mode: str = "jurigged"
    ssl: GrizzlaxySSLConfig = field(default_factory=GrizzlaxySSLConfig)
    oauth: GrizzlaxyOAuthConfig = field(default_factory=GrizzlaxyOAuthConfig)
    sentry: GrizzlaxySentryConfig = field(default_factory=GrizzlaxySentryConfig)

    def __post_init__(self):
        override = os.environ.get("GRIZZLAXY_RELOAD_OVERRIDE", None)
        if override:
            self.host, self.port = json.loads(override)
            self.open_browser = False

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


config = gifnoc.define(field="grizzlaxy", model=GrizzlaxyConfig)
