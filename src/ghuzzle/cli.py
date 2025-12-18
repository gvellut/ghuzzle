import argparse
import os
import shutil
import tarfile

import requests
from github import Auth, Github


def download_and_extract(token, config, build_dir):
    auth = Auth.Token(token)
    g = Github(auth=auth)

    if not os.path.exists(build_dir):
        os.makedirs(build_dir)

    print(f"--- Starting Assembly into '{build_dir}' ---")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",  # Crucial for private binaries
    }

    for item in config:
        repo_name = item["repo"]
        tag = item.get("tag", "latest")
        pattern = item["asset_pattern"]

        print(f"Processing {repo_name} ({tag})...")

        # 2. Locate the Release via PyGithub
        # PyGithub makes finding the correct ID easy
        try:
            repo = g.get_repo(repo_name)
            if tag == "latest":
                release = repo.get_latest_release()
            else:
                release = repo.get_release(tag)
        except Exception as e:
            print(f"  [!] Failed to find repo or release: {e}")
            continue

        # 3. Find the specific asset ID
        target_asset = None
        for asset in release.get_assets():
            if pattern in asset.name:
                target_asset = asset
                break

        if not target_asset:
            print(f"  [!] No asset found matching '{pattern}'")
            continue

        # 4. Download (Using requests for binary stream)
        # We manually construct the URL to ensure we get the binary, not the S3 redirect
        dl_url = f"https://api.github.com/repos/{repo_name}/releases/assets/{target_asset.id}"

        temp_file = os.path.join(build_dir, target_asset.name)

        print(f"  -> Downloading {target_asset.name}...")
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
            print(f"  -> Extracting to {dest_folder}...")
            if temp_file.endswith(".tar.gz") or temp_file.endswith(".tgz"):
                with tarfile.open(temp_file, "r:gz") as tar:
                    tar.extractall(path=dest_folder)
            # Add zipfile logic here if needed

            # Cleanup the tar file
            os.remove(temp_file)
        else:
            # If not extracting, just move/organize the file
            os.makedirs(dest_folder, exist_ok=True)
            shutil.move(temp_file, os.path.join(dest_folder, target_asset.name))

    print("--- Assembly Complete ---")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    # Configuration: Define your dependency tree here
    DEPENDENCIES = [
        {
            "repo": "MyUser/repo-a",
            "tag": "v1.0.0",
            "asset_pattern": ".tar.gz",
            "extract": True,
        },
        {
            "repo": "MyUser/repo-b",
            "tag": "latest",
            "asset_pattern": ".tar.gz",
            "extract": True,
        },
    ]

    download_and_extract(args.token, DEPENDENCIES, "./dist_assembly")


if __name__ == "__main__":
    main()
