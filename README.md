# Ghuzzle

Ghuzzle is a tool to download and assemble dependencies from GitHub releases into a local directory. It supports both public and private repositories via GitHub tokens.

## Installation

Install as a Python package:

```bash
pip install ghuzzle
```

## Usage as CLI

Run the tool with a GitHub token.

```bash
python -m ghuzzle --token YOUR_GITHUB_TOKEN --config deps.json
```

This downloads assets matching patterns from specified repos/tags and extracts them into `./dist`.

## Usage as Python Library

Import and call the `download_and_extract` function:

```python
from ghuzzle import download_and_extract

config = [
    {"repo": "user/repo", "tag": "v1.0", "asset_pattern": "*.tar.gz"}
]
download_and_extract(token="YOUR_TOKEN", config=config, build_dir="./build")
```

## Config file

Provide a JSON list of objects, e.g. `ghuzzle.json`:
- `repo` (required): `owner/name` of the repository.
- `tag` (optional, default `latest`): release tag to use.
- `asset-pattern` (required): shell-style wildcard matched with `fnmatch` (e.g., `myfile*.zip`, `*.txt`, `asdasd*`). Use `source.zip` or `source.tar.gz` for source assets
- `dest` (optional): output subfolder relative to the build-dir input to the action (defaults to the repo name).
- `dir-content` (optional, default `false`): if extraction yields a single directory, flatten it.
- `extract` (optional, default `true`): set to `false` to just copy the asset, even if extractable (zip, tar.gz). If not extractable, will have no effect

Example:

```json
[
    {
        "repo": "gvellut/dmp_midi",
        "tag": "latest",
        "asset-pattern": "dmp_200_mm.zip",
        "dest": "hello"
    },
    ....
]
```

## Usage as GitHub Action

Add to your workflow to assemble dependencies in CI:

```yaml
- uses: your-org/ghuzzle@v1
  with:
    config: path/to/ghuzzle.json  # Optional: custom config file (default: ./ghuzzle.json)
    build-dir: ./dist              # Optional: output directory (default: ./dist)
```

> **Note:** For **public repositories**, you don't need to pass a token. The action will work without authentication to download public release assets.

For private repositories, see the [Access private repo](#access-private-repo) section below.

### Inputs

- `config`: Path to the configuration file (default: `./ghuzzle.json`).
- `build-dir`: Output directory for downloaded assets (default: `./dist`).
- `token`: GitHub token for accessing private repositories (default: `github.token`).
- `ignore-dep-error`: Flag to continue if dependency cannot be found (default: `n`).

### Access the private action ghuzzle from other repo by same user

1.  Go to your **`gvellut/ghuzzle`** repository on GitHub.
2.  Click on **Settings** (top tab).
3.  In the left sidebar, click **Actions** > **General**.
4.  Scroll down to the bottom to find the **Access** section.
5.  Select: **"Accessible from repositories owned by 'gvellut' user"**.
6.  Click **Save**.

## Access private repo 

To access private repositories, you must pass a token to the action via the `token` input. You can use either:
- A **Personal Access Token (PAT)** stored as a repository secret
- A **GitHub App token** generated dynamically in your workflow

### Private Access Token

A Personal Access Token (PAT) allows you to authenticate and download assets from private repositories.

#### How to generate a PAT:

1. Go to your GitHub profile: **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)** or **Fine-grained tokens**.

2. **For Classic tokens:**
   - Click **Generate new token (classic)**.
   - Give it a descriptive name (e.g., `ghuzzle-releases`).
   - Select the `repo` scope (full control of private repositories).
   - Click **Generate token** and copy it immediately.

3. **For Fine-grained tokens (recommended):**
   - Click **Generate new token**.
   - Set the **Token name** and **Expiration**.
   - Under **Repository access**, select **Only select repositories** and choose the private repos you need.
   - Under **Permissions** → **Repository permissions**, set **Contents** to **Read-only**.
   - Click **Generate token** and copy it immediately.

4. **Store the token as a repository secret:**
   - Go to your repository: **Settings** → **Secrets and variables** → **Actions**.
   - Click **New repository secret**.
   - Name it (e.g., `GH_PAT`) and paste your token.

#### Full example with PAT:

```yaml
name: Build with Ghuzzle (PAT)
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download dependencies
        uses: your-org/ghuzzle@v1
        with:
          config: ./ghuzzle.json
          build-dir: ./dist
          token: ${{ secrets.GH_PAT }}  # PAT stored as repository secret
```

### Using a Github App

GitHub Apps provide a more secure and scalable way to authenticate, especially for organizations.

The App ID and private key must be added to the secrets to every repo needing access to the private repositories where releases are stored.

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

7.  **Store credentials as secrets:**
    *   Go to your repository: **Settings** → **Secrets and variables** → **Actions**.
    *   Add `MY_APP_ID` with the App ID value.
    *   Add `MY_APP_PRIVATE_KEY` with the entire contents of the `.pem` file.

#### Full example with GitHub App:

```yaml
name: Build with Ghuzzle (GitHub App)
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Generate GitHub App Token
        uses: actions/create-github-app-token@v1
        id: app-token
        with:
          app-id: ${{ secrets.MY_APP_ID }}
          private-key: ${{ secrets.MY_APP_PRIVATE_KEY }}
          owner: "...owner..."

      - name: Download dependencies
        uses: your-org/ghuzzle@v1
        with:
          config: ./ghuzzle.json
          build-dir: ./dist
          token: ${{ steps.app-token.outputs.token }}  # Token generated from GitHub App
```

**Note**: From the `create-github-app-token` documentation, if `owner` and `repositories` are empty, access will be scoped to only the current repository. If `owner` is set and `repositories` is empty, access will be scoped to all repositories in the provided repository owner's installation (dependent on the accessible repositories configured for App). So to access your arbitrary private repos, set the `owner` to yourself. It is also possible to set it to another user / organization if needed (but all the repos inside a specific config and run of a ghuzzle step should be accessible with the same token).
