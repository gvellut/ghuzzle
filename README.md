# Ghuzzle

Ghuzzle is a tool to download and assemble dependencies from GitHub releases into a local directory. It supports both public and private repositories via GitHub tokens.

## Installation

Install as a Python package:

```bash
pip install ghuzzle
```

## Usage as CLI

Run the tool with a GitHub token. Edit the `DEPENDENCIES` list in `ghuzzle.py` or pass a custom config.

```bash
python -m ghuzzle --token YOUR_GITHUB_TOKEN
```

This downloads assets matching patterns from specified repos/tags and extracts them into `./dist`.

## Usage as Python Library

Import and call the `download_and_extract` function:

```python
from ghuzzle import download_and_extract

config = [
    {"repo": "user/repo", "tag": "v1.0", "asset_pattern": ".tar.gz", "extract": True}
]
download_and_extract(token="YOUR_TOKEN", config=config, build_dir="./build")
```

## Usage as GitHub Action

Add to your workflow to assemble dependencies in CI:

```yaml
- uses: your-org/ghuzzle@v1
  with:
    definition: path/to/ghuzzle.json  # Optional: custom config file : default is ./ghuzzle.json in root of current repo (running the workflow)
```

## Access private repo 

### Private Access Token

TODO

### Using a Github App

1.  **Navigate to Developer Settings:**
    *   Click your profile photo in the top-right corner -> **Settings**.
    *   Scroll down to the bottom of the left sidebar and click **Developer settings**.
    *   Click **GitHub Apps** -> **New GitHub App**.

2.  **App Configuration:**
    *   **GitHub App Name:** `Release-Downloader-Bot` (must be unique globally, so you might need to append your username, e.g., `johndoe-release-bot`).
    *   **Homepage URL:** `https://github.com/your-username` (placeholder).
    *   **Callback URL:** (Leave blank or use the placeholder; uncheck "Active" under Webhook if you don't need webhooks).

3.  **Permissions (Repository permissions):**
    *   Click "Permissions".
    *   Scroll to **Contents**. Change access to **Read-only**.
        *   *Note: This allows the bot to read code, commits, and download release artifacts.*
    *   **Metadata:** `Read-only` (selected by default).

4.  **Create and Save:**
    *   Scroll to the bottom and click **Create GitHub App**.

5.  **Get Credentials:**
    *   **App ID:** You will see this at the top of the "General" page. Copy it.
    *   **Private Key:** Scroll down to "Private keys" and click **Generate a private key**. A `.pem` file will download. Open this with a text editor and copy the *entire* contents.

6.  **Install the App:**
    *   In the left sidebar of your App settings, click **Install App**.
    *   Click **Install** next to your username.
    *   **Repository Access:** Select **All repositories** (for maximum scalability) or **Only select repositories** (ensure Repo A and Repo Z are selected).
    *   Click **Install**.


Embed a token to access the releases of a private repo. Use the **App ID** and **Private Key** copied from above: 

```yaml
- uses: actions/create-github-app-token@v1
    id: app-token
    with:
      app-id: ${{ secrets.MY_APP_ID }}
      private-key: ${{ secrets.MY_APP_PRIVATE_KEY }}
```