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

This downloads assets matching patterns from specified repos/tags and extracts them into `./dist_assembly`.

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
    definition: path/to/definition.json  # Optional: custom config file
    extras: s3,sql  # Optional: comma-separated uv extras for installation
```

This runs Ghuzzle using uv, installing any specified extras.