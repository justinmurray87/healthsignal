"""
Simple wrapper around Tweepy for posting crisis alerts to Twitter/X.

Before using this module, ensure the following environment variables are set:

    TWITTER_CONSUMER_KEY
    TWITTER_CONSUMER_SECRET
    TWITTER_ACCESS_TOKEN
    TWITTER_ACCESS_TOKEN_SECRET

To send a tweet call `post_crisis_tweet(event)`, where `event` is a
dictionary containing at least the keys: location, people_affected,
event_type, summary, donation_links.
"""

import os
from typing import Dict

try:
    import tweepy  # type: ignore
except ImportError:
    tweepy = None  # type: ignore


TWITTER_CONSUMER_KEY = os.environ.get("TWITTER_CONSUMER_KEY")
TWITTER_CONSUMER_SECRET = os.environ.get("TWITTER_CONSUMER_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")


def post_crisis_tweet(event: Dict[str, any]) -> None:
    """Publish a tweet describing a crisis.

    Args:
        event: Dictionary with keys 'location', 'people_affected',
               'event_type', 'summary' and 'donation_links'.
    """
    if tweepy is None:
        raise RuntimeError("tweepy is not installed; cannot post tweets.")
    if not all([
        TWITTER_CONSUMER_KEY,
        TWITTER_CONSUMER_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET,
    ]):
        raise RuntimeError("Twitter API credentials are missing from environment variables.")
    auth = tweepy.OAuth1UserHandler(
        TWITTER_CONSUMER_KEY,
        TWITTER_CONSUMER_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET,
    )
    api = tweepy.API(auth)
    text = (
        f"🚨 Crisis in {event['location']}: {event['people_affected']} affected by "
        f"{event['event_type']}\n"
        f"{event['summary']}\n"
        f"Help: {event['donation_links'][0]}"
    )
    api.update_status(status=text[:280])
    print("Tweet sent:", text[:280])


__all__ = ["post_crisis_tweet"]