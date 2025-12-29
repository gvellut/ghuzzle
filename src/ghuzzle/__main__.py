import json
import logging
from pathlib import Path
import sys
import traceback

import click
import colorama
from colorama import Fore

from .ghuzzle import download_and_extract

logger = logging.getLogger(__package__)

DEFAULT_CONFIG = "ghuzzle.json"
DEFAULT_BUILD_DIR = "dist"


LOG_COLORS = {logging.ERROR: Fore.RED, logging.WARNING: Fore.YELLOW}


class ColorFormatter(logging.Formatter):
    colorama.init()

    def format(self, record, *args, **kwargs):
        if record.levelno in LOG_COLORS:
            record.msg = f"{LOG_COLORS[record.levelno]}{record.msg}{Fore.RESET}"
        return super().format(record, *args, **kwargs)


def setup_logging(is_debug):
    global logger
    if is_debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = ColorFormatter("%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class CatchAllExceptionsCommand(click.Command):
    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except Exception as ex:
            raise UnrecoverableGZError(str(ex), sys.exc_info()) from ex


class UnrecoverableGZError(click.ClickException):
    def __init__(self, message, exc_info):
        super().__init__(message)
        self.exc_info = exc_info

    def show(self):
        logger.error("*** An unrecoverable error occured ***")
        logger.error(self.message)
        logger.debug("".join(traceback.format_exception(*self.exc_info)))


@click.command(
    context_settings={"auto_envvar_prefix": "GZ"}, cls=CatchAllExceptionsCommand
)
@click.option("-f", "--config", default=DEFAULT_CONFIG, show_default=True)
@click.option("-o", "--build-dir", default=DEFAULT_BUILD_DIR, show_default=True)
@click.option("-t", "--token")
@click.option("-d", "--debug", "is_debug", envvar="DEBUG", type=bool)
def main(config, build_dir, token, is_debug):
    setup_logging(is_debug)

    if not Path(config).exists():
        raise click.ClickException(f"File {config} not found")

    with open(config, encoding="utf-8") as f:
        config = json.load(f)

    download_and_extract(config, build_dir, token)


if __name__ == "__main__":
    main()
