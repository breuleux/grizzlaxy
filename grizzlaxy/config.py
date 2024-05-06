from dataclasses import dataclass, field
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
    # Reloading methodology
    reload_mode: str = "jurigged"
    ssl: GrizzlaxySSLConfig = field(default_factory=GrizzlaxySSLConfig)
    oauth: GrizzlaxyOAuthConfig = field(default_factory=GrizzlaxyOAuthConfig)
    sentry: GrizzlaxySentryConfig = field(default_factory=GrizzlaxySentryConfig)


config = gifnoc.define(field="grizzlaxy", model=GrizzlaxyConfig)
