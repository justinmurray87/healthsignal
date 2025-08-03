"""
Helper module for uploading JSON records to an AWS S3 bucket. This module
provides a reusable function for other scripts or interactive use.

Environment variables required:
    S3_ACCESS_KEY    – AWS access key ID
    S3_SECRET_KEY    – AWS secret access key
    S3_BUCKET_NAME   – Name of the S3 bucket

Note: The bucket should be configured for public read access on individual
objects but should not allow listing the bucket contents.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict

try:
    import boto3  # type: ignore
except ImportError:
    boto3 = None  # type: ignore


S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")


def upload_event(event_id: str, data: Dict) -> None:
    """Upload a JSON record for an event to S3.

    The object key is partitioned by date: events/YYYY/MM/DD/event_id.json.

    Args:
        event_id: Unique identifier for the event (e.g. UUID)
        data: Dictionary to serialise as JSON
    """
    if boto3 is None:
        raise RuntimeError("boto3 not installed; cannot upload to S3.")
    if not all([S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET_NAME]):
        raise RuntimeError("S3 credentials are not fully configured in environment variables.")
    now = datetime.now(timezone.utc)
    key = f"events/{now:%Y}/{now:%m}/{now:%d}/{event_id}.json"
    session = boto3.session.Session(
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )
    s3 = session.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=key,
        Body=json.dumps(data).encode("utf-8"),
        ContentType="application/json",
        ACL="public-read",
    )
    print(f"Uploaded event record to s3://{S3_BUCKET_NAME}/{key}")


__all__ = ["upload_event"]