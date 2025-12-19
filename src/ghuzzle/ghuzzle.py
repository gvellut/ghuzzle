import logging
import os
import shutil
import tarfile
import traceback
import zipfile

from github import Auth, Github, GithubIntegration
import requests

logger = logging.getLogger(__name__)


LATEST = "latest"


def get_app_token(app_id, private_key_pem, owner, repo):
    auth = Auth.AppAuth(
        app_id=app_id,
        private_key=private_key_pem,
    )
    gi = GithubIntegration(auth=auth)

    installation = gi.get_installation(owner, repo)

    return gi.get_access_token(installation.id).token


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


def download_and_extract(config, build_dir, token):
    os.makedirs(build_dir, exist_ok=True)

    auth = Auth.Token(token) if token else None
    if not auth:
        logger.warning("No auth configured")

    g = Github(auth=auth)

    for item in config:
        try:
            repo_name = item["repo"]
            tag = item.get("tag", LATEST)
            asset_pattern = item["asset_pattern"]
            dest_folder = item.get("dest")

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

            # fallback : source release ?
            # TODO make it an option. Error otherwise
            if not target_asset:
                if any(p in asset_pattern for p in ["source", "zip"]):
                    target_asset = type(
                        "Asset",
                        (),
                        {"name": "source.zip", "id": None, "url": release.zipball_url},
                    )
                elif any(p in asset_pattern for p in ["tar", "gz"]):
                    target_asset = type(
                        "Asset",
                        (),
                        {
                            "name": "source.tar.gz",
                            "id": None,
                            "url": release.tarball_url,
                        },
                    )

            if not target_asset:
                logger.error(f"No asset found matching '{asset_pattern}'")
                continue

            dl_url, dl_headers = _get_download_info(repo_name, target_asset, token)

            temp_file = os.path.join(build_dir, target_asset.name)

            if not os.path.exists(temp_file):
                logger.info(f"Downloading {target_asset.name}...")
                with requests.get(dl_url, headers=dl_headers, stream=True) as r:
                    r.raise_for_status()
                    with open(temp_file, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)

            # Extract/Assemble
            # We extract it into a subfolder named after the repo to keep things clean
            if dest_folder:
                dest_folder = os.path.join(build_dir, dest_folder)
            else:
                dest_folder = os.path.join(build_dir, repo_name.split("/")[-1])

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
                # os.remove(temp_file)
            else:
                # If not extracting, just move/organize the file
                os.makedirs(dest_folder, exist_ok=True)
                shutil.move(temp_file, os.path.join(dest_folder, target_asset.name))

        except Exception as e:
            msg = "Empty repo" if not item.get("repo") else f"Error processing {repo}"
            logger.error(msg)
            logger.debug("".join(traceback.format_exception(e)))
