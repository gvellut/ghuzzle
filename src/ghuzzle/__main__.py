import json
import logging
from pathlib import Path
import sys
import traceback

import click
import colorama
from colorama import Fore

from .ghuzzle import (
    DEFAULT_SUMMARY_PATH,
    download_and_extract,
    generate_listing,
    get_listing_output_dir,
    output_summary as write_summary,
)

logger = logging.getLogger(__package__)

# same default as in action.yml
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
@click.option(
    "--ignore-dep-error",
    is_flag=True,
    default=False,
    help="Continue if a dependency cannot be downloaded (default: abort on error)",
)
@click.option(
    "--output-summary",
    "output_summary_opt",
    default=None,
    help=(
        "Output a JSON summary of results. "
        f"Use 'true' for default path ({DEFAULT_SUMMARY_PATH}) "
        "or specify a custom path."
    ),
)
@click.option(
    "--gen-listing",
    default=None,
    help=(
        "Generate an index.html listing page. "
        "Use 'true' for default location (common dest prefix or 'ghuzzle' folder) "
        "or specify a custom directory path."
    ),
)
@click.option(
    "--gen-listing-config",
    default=None,
    type=click.Path(exists=True),
    help=(
        "Path to a JSON config file for the listing page "
        "(title, homepage, homepage-title)."
    ),
)
def main(
    config,
    build_dir,
    token,
    is_debug,
    ignore_dep_error,
    output_summary_opt,
    gen_listing,
    gen_listing_config,
):
    setup_logging(is_debug)

    if not Path(config).exists():
        raise click.ClickException(f"File {config} not found")

    with open(config, encoding="utf-8") as f:
        config_data = json.load(f)

    results = download_and_extract(config_data, build_dir, token, ignore_dep_error)

    # Handle output-summary
    if output_summary_opt:
        summary_path = (
            DEFAULT_SUMMARY_PATH
            if output_summary_opt.lower() in ("true", "y", "yes", "1")
            else output_summary_opt
        )
        write_summary(results, summary_path)

    # Handle gen-listing
    if gen_listing:
        if gen_listing.lower() in ("true", "y", "yes", "1"):
            listing_dir = get_listing_output_dir(config_data, build_dir)
        else:
            listing_dir = gen_listing

        # Load listing config if provided
        listing_config = None
        if gen_listing_config:
            with open(gen_listing_config, encoding="utf-8") as f:
                listing_config = json.load(f)

        generate_listing(results, listing_dir, listing_config)


if __name__ == "__main__":
    main()
