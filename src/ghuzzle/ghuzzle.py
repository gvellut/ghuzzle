from __future__ import annotations

import fnmatch
import json
import logging
import os
from pathlib import Path
import random
import re
import shutil
import tarfile
import tempfile
import traceback
from typing import TYPE_CHECKING
import zipfile

import attr
from github import Auth, Github, GithubIntegration
from htpy import a, body, div, h1, head, html, link, meta, span, style, title
from markupsafe import Markup
import requests

if TYPE_CHECKING:
    from github.GitRelease import GitRelease
    from github.GitReleaseAsset import GitReleaseAsset
    from github.Repository import Repository

logger = logging.getLogger(__name__)


LATEST = "latest"

# Extractable file extensions
EXTRACTABLE_EXTENSIONS = {".tar.gz", ".tgz", ".zip", ".tar", ".tar.bz2", ".tar.xz"}

# JSON config keys
CONFIG_KEY_REPO = "repo"
CONFIG_KEY_TAG = "tag"
CONFIG_KEY_ASSET_PATTERN = "asset-pattern"
CONFIG_KEY_DEST = "dest"
CONFIG_KEY_DIR_CONTENT = "dir-content"
CONFIG_KEY_DISPLAY_NAME = "display-name"
CONFIG_KEY_COLOR = "color"

# Config color value for random
CONFIG_COLOR_RANDOM = "random"

SOURCE_ZIP = "source.zip"
SOURCE_TAR_GZ = "source.tar.gz"

# Summary output keys
SUMMARY_KEY_REPO = "repo"
SUMMARY_KEY_REPO_SHORT = "repo-short"
SUMMARY_KEY_DESCRIPTION = "description"
SUMMARY_KEY_URL = "url"
SUMMARY_KEY_TOPICS = "topics"
SUMMARY_KEY_TAG = "tag"
SUMMARY_KEY_TITLE = "title"
SUMMARY_KEY_NOTES = "notes"
SUMMARY_KEY_FILENAME = "filename"
SUMMARY_KEY_DATE = "date"
SUMMARY_KEY_DEST = "dest"
SUMMARY_KEY_REPO_OK = "repo-ok"
SUMMARY_KEY_RELEASE_OK = "release-ok"
SUMMARY_KEY_ASSET_OK = "asset-ok"
SUMMARY_KEY_DOWNLOAD_OK = "download-ok"
SUMMARY_KEY_DISPLAY_NAME = "display-name"
SUMMARY_KEY_COLOR = "color"

# Listing config keys
LISTING_CONFIG_KEY_TITLE = "title"
LISTING_CONFIG_KEY_HOMEPAGE = "homepage"
LISTING_CONFIG_KEY_HOMEPAGE_TITLE = "homepage-title"

# Default values
DEFAULT_CONFIG = "ghuzzle.json"
DEFAULT_BUILD_DIR = "dist"
DEFAULT_SUMMARY_PATH = "ghuzzle-summary.json"
DEFAULT_LISTING_DIR = "ghuzzle"

# Regex for validating hex color (6 hex digits)
HEX_COLOR_REGEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


class AssetNotFoundError(Exception):
    pass


class AssetProcessingError(Exception):
    pass


class FatalDependencyError(Exception):
    pass


def _parse_color(color_value, repo_name):
    """Parse and validate a color value from config.

    Args:
        color_value: The color string from config (hex with/without #, or "random")
        repo_name: The repo name for logging purposes

    Returns:
        A valid hex color string with # prefix, or None if invalid/not provided.
    """
    if not color_value:
        return None

    # Handle "random" value
    if color_value.lower() == CONFIG_COLOR_RANDOM:
        return _generate_random_color()

    # Validate and normalize hex color
    match = HEX_COLOR_REGEX.match(color_value.strip())
    if match:
        return f"#{match.group(1).lower()}"

    # Bad format - log warning
    logger.warning(f"Invalid color format '{color_value}' for {repo_name}, ignoring")
    return None


def _generate_random_color():
    """Generate a random hex color for UI purposes."""
    # Using random (not secrets) is acceptable here - this is purely for visual display
    return f"#{random.randint(0, 0xFFFFFF):06x}"


def _is_extractable(filename):
    """Check if the file has an extractable extension."""
    lower_name = filename.lower()
    for ext in EXTRACTABLE_EXTENSIONS:
        if lower_name.endswith(ext):
            return True
    return False


def _get_temp_dir():
    """Get the temp directory for downloads.

    Uses RUNNER_TEMP for GitHub Actions, system temp otherwise.
    """
    return os.environ.get("RUNNER_TEMP", tempfile.gettempdir())


def _flatten_single_dir(dest_folder, ignore_dep_error):
    """
    If dest_folder contains only a single directory, move its contents up
    and remove the empty directory.
    """
    contents = os.listdir(dest_folder)
    if len(contents) == 1:
        single_item = os.path.join(dest_folder, contents[0])
        if os.path.isdir(single_item):
            # Move all contents from the single directory up to dest_folder
            for item in os.listdir(single_item):
                src = os.path.join(single_item, item)
                dst = os.path.join(dest_folder, item)
                shutil.move(src, dst)
            # Remove the now-empty single directory
            os.rmdir(single_item)
            logger.info(f"Flattened single directory '{contents[0]}' in {dest_folder}")
            return True

    if not ignore_dep_error:
        raise AssetProcessingError("Flatten error: unable to flatten content")

    return False


def get_app_token(app_id, private_key_pem, owner, repo):
    auth = Auth.AppAuth(
        app_id=app_id,
        private_key=private_key_pem,
    )
    gi = GithubIntegration(auth=auth)

    installation = gi.get_installation(owner, repo)

    return gi.get_access_token(installation.id).token


def _extract_asset(temp_file, dest_folder):
    if temp_file.endswith(".tar.gz") or temp_file.endswith(".tgz"):
        with tarfile.open(temp_file, "r:gz") as tar:
            tar.extractall(path=dest_folder)
    elif temp_file.endswith(".tar.bz2"):
        with tarfile.open(temp_file, "r:bz2") as tar:
            tar.extractall(path=dest_folder)
    elif temp_file.endswith(".tar.xz"):
        with tarfile.open(temp_file, "r:xz") as tar:
            tar.extractall(path=dest_folder)
    elif temp_file.endswith(".tar"):
        with tarfile.open(temp_file, "r:") as tar:
            tar.extractall(path=dest_folder)
    elif temp_file.endswith(".zip"):
        with zipfile.ZipFile(temp_file, "r") as zip_ref:
            zip_ref.extractall(dest_folder)


def _get_download_info(repo_name, target_asset, token):
    if not target_asset.id:
        # Source code zipball/tarball
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return target_asset.url, headers

    if token:
        # Private or public asset with token
        dl_url = f"https://api.github.com/repos/{repo_name}/releases/assets/{target_asset.id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/octet-stream",
        }
        return dl_url, headers
    else:
        # Public asset without token
        return target_asset.browser_download_url, {}


@attr.define
class FindResult:
    """Result from _find_asset with repo, release, and asset info."""

    repo_name: str
    repo: Repository = None
    release: GitRelease = None
    asset: GitReleaseAsset = None
    repo_ok: bool = False
    release_ok: bool = False
    asset_ok: bool = False


def _find_asset(g: Github, repo_name, tag, asset_pattern):
    logger.info(f"Processing {repo_name} ({tag})...")

    result = FindResult(repo_name)

    # locate the Repo
    try:
        repo = g.get_repo(repo_name)
        result.repo = repo
        result.repo_ok = True
    except Exception as e:
        logger.error(f"Failed to find repo: {e}")
        logger.debug("".join(traceback.format_exception(e)))
        return result

    # locate the Release
    try:
        if tag == LATEST:
            release = repo.get_latest_release()
        elif any(c in tag for c in "*?[]"):
            # Wildcard search in tags or titles
            release = None
            for r in repo.get_releases():
                if fnmatch.fnmatch(r.tag_name, tag) or (
                    r.name and fnmatch.fnmatch(r.name, tag)
                ):
                    release = r
                    break
            if not release:
                raise AssetNotFoundError(f"No release found matching pattern: {tag}")
        else:
            release = repo.get_release(tag)
        result.release = release
        result.release_ok = True
    except Exception as e:
        logger.error(f"Failed to find release: {e}")
        logger.debug("".join(traceback.format_exception(e)))
        return result

    # Find the specific asset ID
    target_asset = None
    for asset in release.get_assets():
        if fnmatch.fnmatch(asset.name, asset_pattern):
            target_asset = asset
            break

    # fallback : source release : default generated by GH
    if not target_asset:
        if asset_pattern == SOURCE_ZIP:
            target_asset = type(
                "Asset",
                (),
                {
                    "name": SOURCE_ZIP,
                    "id": None,
                    "url": release.zipball_url,
                },
            )
        elif asset_pattern == SOURCE_TAR_GZ:
            target_asset = type(
                "Asset",
                (),
                {
                    "name": SOURCE_TAR_GZ,
                    "id": None,
                    "url": release.tarball_url,
                },
            )

    if target_asset:
        result.asset = target_asset
        result.asset_ok = True

    return result


def _download_asset(repo_name, target_asset, temp_dir, token):
    dl_url, dl_headers = _get_download_info(repo_name, target_asset, token)

    # Download to temp directory (RUNNER_TEMP or system temp)
    temp_file = os.path.join(temp_dir, target_asset.name)

    if not os.path.exists(temp_file):
        logger.info(f"Downloading {target_asset.name}...")
        with requests.get(dl_url, headers=dl_headers, stream=True) as r:
            r.raise_for_status()
            with open(temp_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    return temp_file


def _build_result_entry(
    repo_name,
    dest_folder,
    find_result: FindResult,
    download_ok=False,
    display_name=None,
    color=None,
):
    """Build a result entry dictionary from find_result data."""
    entry = {
        SUMMARY_KEY_REPO: repo_name,
        SUMMARY_KEY_REPO_OK: find_result.repo_ok,
        SUMMARY_KEY_RELEASE_OK: find_result.release_ok,
        SUMMARY_KEY_ASSET_OK: find_result.asset_ok,
        SUMMARY_KEY_DOWNLOAD_OK: download_ok,
    }

    if find_result.repo_ok and find_result.repo:
        repo = find_result.repo
        entry[SUMMARY_KEY_REPO_SHORT] = repo.name
        entry[SUMMARY_KEY_DESCRIPTION] = repo.description
        entry[SUMMARY_KEY_URL] = repo.html_url
        entry[SUMMARY_KEY_TOPICS] = repo.get_topics()

    if find_result.release_ok and find_result.release:
        release = find_result.release
        entry[SUMMARY_KEY_TAG] = release.tag_name
        entry[SUMMARY_KEY_TITLE] = release.title
        entry[SUMMARY_KEY_NOTES] = release.body
        if release.published_at:
            entry[SUMMARY_KEY_DATE] = release.published_at.isoformat()
        else:
            entry[SUMMARY_KEY_DATE] = None

    if find_result.asset_ok and find_result.asset:
        entry[SUMMARY_KEY_FILENAME] = find_result.asset.name

    if dest_folder:
        entry[SUMMARY_KEY_DEST] = dest_folder

    if display_name:
        entry[SUMMARY_KEY_DISPLAY_NAME] = display_name

    if color:
        entry[SUMMARY_KEY_COLOR] = color

    return entry


def download_and_extract(config, build_dir, token, ignore_dep_error=False):
    os.makedirs(build_dir, exist_ok=True)
    base_temp_dir = _get_temp_dir()

    auth = Auth.Token(token) if token else None
    if not auth:
        logger.warning("No auth configured")
    elif token.startswith("ghs_"):
        logger.info("Using GitHub App or Actions token")
    else:
        logger.info("Using Personal Access Token")

    g = Github(auth=auth)
    has_errors = False
    results = []

    with tempfile.TemporaryDirectory(dir=base_temp_dir) as temp_dir:
        for item in config:
            repo_name = item[CONFIG_KEY_REPO]
            tag = item.get(CONFIG_KEY_TAG, LATEST)
            asset_pattern = item[CONFIG_KEY_ASSET_PATTERN]
            dest_folder = item.get(CONFIG_KEY_DEST)
            dir_content = item.get(CONFIG_KEY_DIR_CONTENT, False)
            display_name = item.get(CONFIG_KEY_DISPLAY_NAME)
            color = _parse_color(item.get(CONFIG_KEY_COLOR), repo_name)

            # Initialize find_result for error handling
            find_result = FindResult(repo_name)

            try:
                find_result = _find_asset(g, repo_name, tag, asset_pattern)

                if not find_result.asset_ok:
                    msg = f"No asset found for {repo_name}"
                    if ignore_dep_error:
                        logger.error(msg)
                        logger.warning("Continuing due to --ignore-dep-error flag")
                        # Record partial result
                        results.append(
                            _build_result_entry(
                                repo_name,
                                dest_folder,
                                find_result,
                                display_name=display_name,
                                color=color,
                            )
                        )
                        has_errors = True
                        continue
                    else:
                        raise AssetNotFoundError(msg)

                target_asset = find_result.asset
                temp_file = _download_asset(repo_name, target_asset, temp_dir, token)

                # Extract/Assemble
                final_dest_folder = dest_folder
                if dest_folder:
                    final_dest_folder = os.path.join(build_dir, dest_folder)
                else:
                    # not separated from the others. Use explicit name if want to
                    # extract to dir with repo name
                    final_dest_folder = build_dir

                # Determine if the file is extractable
                is_extractable = _is_extractable(temp_file)
                # extract defaults to True, but user can explicitly set to False
                should_extract = item.get("extract", True)

                if should_extract and is_extractable:
                    logger.info(f"Extracting to {final_dest_folder}...")

                    # Extract to a temporary staging directory first
                    staging_dir = tempfile.mkdtemp(dir=temp_dir, prefix="staging_")
                    _extract_asset(temp_file, staging_dir)

                    # Handle dir-content option: flatten if only one directory
                    if dir_content:
                        _flatten_single_dir(staging_dir, ignore_dep_error)

                    # Merge contents from staging to final destination
                    os.makedirs(final_dest_folder, exist_ok=True)
                    for item_name in os.listdir(staging_dir):
                        src = os.path.join(staging_dir, item_name)
                        dst = os.path.join(final_dest_folder, item_name)
                        if os.path.isdir(src):
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, dst)
                else:
                    # Not extracting: either extract=False or not an extractable format
                    if should_extract and not is_extractable:
                        ext = os.path.splitext(temp_file)[1] if "." in temp_file else ""
                        if not ignore_dep_error:
                            msg = (
                                f"Extraction requested but '{ext}' files not "
                                "extractable."
                            )
                            raise AssetProcessingError(msg)
                        msg = (
                            f"Cannot extract '{ext}' files. Copying to destination "
                            "instead."
                        )
                        logger.warning(msg)

                    # Copy file to destination folder
                    os.makedirs(final_dest_folder, exist_ok=True)
                    dest_path = os.path.join(final_dest_folder, target_asset.name)
                    shutil.copy2(temp_file, dest_path)
                    logger.info(f"Copied {target_asset.name} to {final_dest_folder}")

                # Record successful result
                results.append(
                    _build_result_entry(
                        repo_name,
                        dest_folder,
                        find_result,
                        download_ok=True,
                        display_name=display_name,
                        color=color,
                    )
                )

            except Exception as e:
                msg = f"Error processing {repo_name}: {e}"

                if not ignore_dep_error:
                    raise FatalDependencyError(f"Dependency error: {msg}") from e

                logger.error(msg)
                logger.debug("".join(traceback.format_exception(e)))
                logger.warning("Continuing due to --ignore-dep-error flag")

                # Record partial result with download failure
                results.append(
                    _build_result_entry(
                        repo_name,
                        dest_folder,
                        find_result,
                        display_name=display_name,
                        color=color,
                    )
                )
                has_errors = True

    if has_errors:
        logger.warning("Completed with errors (ignored due to --ignore-dep-error flag)")

    return results


def output_summary(results, output_path):
    """Write the results to a JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Summary written to: {output_path}")


def _get_common_prefix(paths):
    """Get the common prefix path from a list of paths."""
    if not paths:
        return None

    # Normalize paths and split into parts
    path_parts = [Path(p).parts for p in paths if p]

    if not path_parts:
        return None

    # Find common prefix
    common_parts = []
    for parts in zip(*path_parts, strict=False):
        if len(set(parts)) == 1:
            common_parts.append(parts[0])
        else:
            break

    if not common_parts:
        return None

    return str(Path(*common_parts))


def get_common_dir(config):
    """Determine the output directory for the listing based on config dest paths."""
    dest_paths = [item.get(CONFIG_KEY_DEST) for item in config]

    # assume they have a different dest each
    if all(dest_paths) and len(dest_paths) > 1:
        common_prefix = _get_common_prefix(dest_paths)
        if common_prefix:
            return common_prefix

    return None


def _load_css():
    """Load CSS from external file."""
    css_path = Path(__file__).parent / "listing.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return ""


def generate_listing(
    results, build_dir, output_dir, is_listing_explicit, listing_config=None
):
    """Generate an index.html listing page from the results."""
    output_path = Path(output_dir) / "index.html"

    if not is_listing_explicit and output_path.exists():
        logger.error(f"Listing file already exists: {output_path}")
        return False

    # Load config
    page_title = None
    homepage = None
    homepage_title = None
    if listing_config:
        page_title = listing_config.get(LISTING_CONFIG_KEY_TITLE)
        homepage = listing_config.get(LISTING_CONFIG_KEY_HOMEPAGE)
        homepage_title = listing_config.get(LISTING_CONFIG_KEY_HOMEPAGE_TITLE)

    # Load CSS
    css_content = _load_css()

    # Build grid items
    items = []
    for i, result in enumerate(results):
        if not result.get(SUMMARY_KEY_DOWNLOAD_OK):
            continue

        # Use display_name if available, otherwise fallback to repo_short
        item_title = result.get(SUMMARY_KEY_DISPLAY_NAME) or result.get(
            SUMMARY_KEY_REPO_SHORT
        )

        logger.info(f"Tile {item_title}")

        dest = result.get(SUMMARY_KEY_DEST)
        if dest:
            # suppose dist hierarchy is the one on the final server
            dest = "/" + dest
        else:
            dest = "/"

        link_href = dest

        # Check for custom color
        custom_color = result.get(SUMMARY_KEY_COLOR)
        if custom_color:
            # Use custom color with dimming overlay
            item = a(href=link_href)[
                div(
                    class_="grid-item custom-color",
                    style=f"--custom-bg-color: {custom_color};",
                )[span[item_title]]
            ]
        else:
            # Use default color scheme
            color_index = i % 6
            item = a(href=link_href)[
                div(class_=f"grid-item color-{color_index}")[span[item_title]]
            ]
        items.append(item)

    # Build page structure
    header_element = None
    if page_title:
        header_element = h1(class_="page-title")[page_title]

    footer_element = None
    if homepage:
        footer_text = homepage_title if homepage_title else homepage
        footer_element = div(class_="footer")[a(href=homepage)[footer_text]]

    page = html(lang="en")[
        head[
            meta(charset="UTF-8"),
            meta(name="viewport", content="width=device-width, initial-scale=1.0"),
            link(rel="icon", href="/favicon.svg", type="image/svg+xml"),
            title[page_title] if page_title else title[""],
            style[Markup(css_content)],
        ],
        body[
            header_element,
            div(class_="grid-container")[items],
            footer_element,
        ],
    ]

    # Write to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html>\n")
        f.write(str(page))

    logger.info(f"Listing page generated: {output_path}")
    return True
