#!/usr/bin/env bash
#
# Deploy the HelpSignal frontend to GitHub Pages. This script assumes that
# your repository has a remote named "origin" and that GitHub Pages is
# configured to serve the gh-pages branch. It uses git subtree to push the
# contents of the `frontend` directory to the gh-pages branch.

set -euo pipefail

# Ensure we're inside the repo root
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$REPO_ROOT"

BRANCH="gh-pages"
FOLDER="frontend"

echo "Deploying ${FOLDER} to GitHub Pages branch ${BRANCH}..."

# Commit any outstanding changes in the frontend directory (optional)
git add "$FOLDER"
git commit -m "Deploy frontend to GitHub Pages" || true

# Create the gh-pages branch if it doesn't exist
if ! git show-ref --verify --quiet refs/heads/${BRANCH}; then
  git branch ${BRANCH} || true
fi

# Use subtree push to deploy the frontend folder
git subtree push --prefix "$FOLDER" origin ${BRANCH}

echo "Deployment complete."