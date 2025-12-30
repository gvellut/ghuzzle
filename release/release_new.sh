#!/usr/bin/env bash

if [ -z "$1" ]; then
  echo "Error: No release tag provided."
  echo "Usage: $0 <tag_name>"
  exit 1
fi

RELEASE_TAG="v$1"

# Check if the release already exists
if gh release view "$RELEASE_TAG" > /dev/null 2>&1; then
  echo "Release '$RELEASE_TAG' already exists. Deleting it first..."
  if gh release delete "$RELEASE_TAG" --yes; then
    echo "Successfully deleted existing release '$RELEASE_TAG'."
  else
    echo "Failed to delete existing release '$RELEASE_TAG'. Aborting."
    exit 1
  fi
fi

gh release create "$RELEASE_TAG" --fail-on-no-commits --generate-notes --title "$RELEASE_TAG"
