#!/usr/bin/env bash
#
# Deploy the HelpSignal backend as a Google Cloud Function. This script
# requires the gcloud CLI to be installed and authenticated. Make sure you
# have created a GCP project and enabled the Cloud Functions API, Sheets API
# and IAM API as described in the README.

set -euo pipefail

FUNCTION_NAME="helpsignal-backend"
REGION="us-west1"
RUNTIME="python311"
ENTRY_POINT="main"
SOURCE_DIR="$(dirname "$0")/.."

echo "Deploying Cloud Function ${FUNCTION_NAME} from ${SOURCE_DIR}..."

# Read environment variables from .env file if present
if [ -f "${SOURCE_DIR}/.env" ]; then
  echo "Loading environment variables from .env..."
  # shellcheck disable=SC1090
  source "${SOURCE_DIR}/.env"
fi

if [ -z "${GOOGLE_SERVICE_ACCOUNT_JSON:-}" ]; then
  echo "GOOGLE_SERVICE_ACCOUNT_JSON is not set. Please specify the path to the service account JSON file in the .env file."
  exit 1
fi

# Deploy the function with environment variables. Add additional variables as needed.
DEPLOY_CMD=(gcloud functions deploy "$FUNCTION_NAME"
  --region "$REGION"
  --runtime "$RUNTIME"
  --trigger-http
  --allow-unauthenticated
  --entry-point "$ENTRY_POINT"
  --source "$SOURCE_DIR/scripts"
  --set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY},NEWS_API_KEY=${NEWS_API_KEY},OPENCAGE_API_KEY=${OPENCAGE_API_KEY},GOOGLE_SHEET_ID=${GOOGLE_SHEET_ID},GCS_BUCKET_NAME=${GCS_BUCKET_NAME},TWITTER_CONSUMER_KEY=${TWITTER_CONSUMER_KEY},TWITTER_CONSUMER_SECRET=${TWITTER_CONSUMER_SECRET},TWITTER_ACCESS_TOKEN=${TWITTER_ACCESS_TOKEN},TWITTER_ACCESS_TOKEN_SECRET=${TWITTER_ACCESS_TOKEN_SECRET},GOOGLE_SERVICE_ACCOUNT_JSON=${GOOGLE_SERVICE_ACCOUNT_JSON}")

# If FUNCTION_SERVICE_ACCOUNT is set in the environment, include it in the deploy
if [ -n "${FUNCTION_SERVICE_ACCOUNT:-}" ]; then
  DEPLOY_CMD+=(--service-account "$FUNCTION_SERVICE_ACCOUNT")
fi

"${DEPLOY_CMD[@]}"

echo "Function deployed."