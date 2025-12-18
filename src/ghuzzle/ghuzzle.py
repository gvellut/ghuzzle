import logging
import os
import shutil
import tarfile
import traceback
import zipfile

from github import Auth, Github
import requests

logger = logging.getLogger(__name__)


LATEST = "latest"


def download_and_extract(token, config, build_dir):
    auth = Auth.Token(token)
    g = Github(auth=auth)

    os.makedirs(build_dir, exist_ok=True)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",  # Crucial for private binaries
    }

    for item in config:
        repo_name = item["repo"]
        tag = item.get("tag", LATEST)
        asset_pattern = item["asset_pattern"]

        logger.info(f"Processing {repo_name} ({tag})...")

        # locate the Release
        try:
            repo = g.get_repo(repo_name)
            if tag == LATEST:
                release = repo.get_latest_release()
            else:
                release = repo.get_release(tag)
        except Exception as e:
            logger.error(f"Failed to find repo or release: {e}")
            logger.debug("".join(traceback.format_exception(e)))
            continue

        # Find the specific asset ID
        target_asset = None
        for asset in release.get_assets():
            if asset_pattern in asset.name:
                target_asset = asset
                break

        if not target_asset:
            logger.error(f"No asset found matching '{asset_pattern}'")
            continue

        # download (Using requests for binary stream)
        # we manually construct the URL to ensure we get the binary, not the S3 redirect
        dl_url = f"https://api.github.com/repos/{repo_name}/releases/assets/{target_asset.id}"

        temp_file = os.path.join(build_dir, target_asset.name)

        logger.info(f"Downloading {target_asset.name}...")
        with requests.get(dl_url, headers=headers, stream=True) as r:
            r.raise_for_status()
            with open(temp_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # 5. Extract/Assemble
        # We extract it into a subfolder named after the repo to keep things clean
        dest_folder = os.path.join(
            build_dir, repo_name.split("/")[-1]
        )  # e.g. downloads/repo-a

        if item.get("extract", True):
            logger.info(f"Extracting to {dest_folder}...")
            if temp_file.endswith(".tar.gz") or temp_file.endswith(".tgz"):
                with tarfile.open(temp_file, "r:gz") as tar:
                    tar.extractall(path=dest_folder)
            elif temp_file.endswith(".zip"):
                with zipfile.ZipFile(temp_file, "r") as zip_ref:
                    zip_ref.extractall(dest_folder)
            else:
                ext = ""
                if "." in temp_file:
                    ext = os.path.splitext(temp_file)[1]
                logger.warning(f"Not programmed to extract '{ext}' archives")

            # Cleanup the downloaded file
            os.remove(temp_file)
        else:
            # If not extracting, just move/organize the file
            os.makedirs(dest_folder, exist_ok=True)
            shutil.move(temp_file, os.path.join(dest_folder, target_asset.name))
