import argparse
import sys

import gifnoc
from gifnoc import Command, Option

from .config import config as gzconfig
from .utils import UsageError


def main(argv=None):
    with gifnoc.cli(
        argparser=argparse.ArgumentParser(description="Start a grizzlaxy of starbears."),
        options=Command(
            mount="grizzlaxy",
            options={
                ".root": "--root",
                ".module": Option(aliases=["--module", "-m"]),
                ".port": Option(aliases=["--port", "-p"]),
                ".host": "--host",
                ".oauth.permissions": "--permissions",
                ".ssl.keyfile": "--ssl-keyfile",
                ".ssl.certfile": "--ssl-certfile",
                ".dev": Option(aliases=["--dev", "-d"]),
                ".reload_mode": "--reload-mode",
                ".watch": "--watch",
                ".open_browser": "--browser",
            },
        ),
        argv=sys.argv[1:] if argv is None else argv,
    ):
        try:
            gzconfig.run()
        except UsageError as exc:
            exit(f"ERROR: {exc}")
        except FileNotFoundError as exc:
            exit(f"ERROR: File not found: {exc}")
