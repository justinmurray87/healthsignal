#!/usr/bin/env bash
#
# Helper script to create and configure a Google Cloud Storage bucket for
# HelpSignal. This script must be run with the gcloud CLI and requires
# appropriate permissions on your GCP project.
#
# The bucket will allow public read access on objects, but listing the
# contents of the bucket will remain restricted. Replace BUCKET_NAME and
# PROJECT_ID with your own values before running.

set -euo pipefail

BUCKET_NAME="helpsignal-archive"
PROJECT_ID="helpsignal"
REGION="us-west1"

echo "Creating bucket gs://${BUCKET_NAME} in project ${PROJECT_ID}..."

# Create the bucket
gsutil mb -p "$PROJECT_ID" -l "$REGION" gs://"$BUCKET_NAME"/

echo "Setting bucket IAM policy to allow public read on objects..."

# Grant allUsers the objectViewer role on the bucket; this allows anyone to read
# objects if they know the full URL but does not allow listing.
gsutil iam ch allUsers:objectViewer gs://"$BUCKET_NAME"

echo "Bucket configured. Upload a test file and verify that it is publicly accessible via its URL."
