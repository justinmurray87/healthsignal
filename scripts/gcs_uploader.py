"""
Helper module for uploading JSON records to a Google Cloud Storage bucket.
This module provides a reusable function for other scripts or interactive use.

Environment variables required:
    GCS_BUCKET_NAME   – Name of the Cloud Storage bucket
    GOOGLE_SERVICE_ACCOUNT_JSON – Path to service account credentials

Note: When running inside Google Cloud Functions or other GCP services,
the default service account is used automatically and the credentials
argument may be omitted.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict

try:
    from google.cloud import storage  # type: ignore
except ImportError:
    storage = None  # type: ignore


GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")


def upload_event(event_id: str, data: Dict) -> None:
    """Upload a JSON record for an event to Google Cloud Storage.

    The object key is partitioned by date: events/YYYY/MM/DD/event_id.json.

    Args:
        event_id: Unique identifier for the event (e.g. UUID)
        data: Dictionary to serialise as JSON
    """
    if storage is None:
        raise RuntimeError("google-cloud-storage is not installed; cannot upload to GCS.")
    if not GCS_BUCKET_NAME:
        raise RuntimeError("GCS_BUCKET_NAME environment variable is not set.")
    now = datetime.now(timezone.utc)
    key = f"events/{now:%Y}/{now:%m}/{now:%d}/{event_id}.json"
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(key)
    blob.upload_from_string(json.dumps(data), content_type="application/json")
    blob.make_public()
    print(f"Uploaded event record to gs://{GCS_BUCKET_NAME}/{key}")


__all__ = ["upload_event"]