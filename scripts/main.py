"""
Main orchestration script for the HelpSignal backend.

This module is designed to run as a Google Cloud Function. It fetches
recent news articles, classifies each one for humanitarian crises,
estimates impact, generates a summary, suggests donation links, geocodes
locations, writes a structured row to a Google Sheet, and archives the
full event data in a Google Cloud Storage (GCS) bucket. Optionally, it
can also tweet about the crisis via a separate tweet bot.

Environment variables required:

OPENAI_API_KEY          – API key for OpenAI (GPT models)
NEWS_API_KEY            – API key for NewsAPI (optional, else RSS)
OPENCAGE_API_KEY        – API key for geocoding via OpenCage
GOOGLE_SERVICE_ACCOUNT_JSON – Path to service account JSON for Google Sheets
GOOGLE_SHEET_ID         – ID of the Google Sheet to write events to
GCS_BUCKET_NAME         – Name of the Google Cloud Storage bucket for JSON archive
TWITTER_CONSUMER_KEY    – (optional) Twitter consumer key for tweeting
TWITTER_CONSUMER_SECRET – (optional) Twitter consumer secret
TWITTER_ACCESS_TOKEN    – (optional) Twitter access token
TWITTER_ACCESS_TOKEN_SECRET – (optional) Twitter access token secret

The Google Sheet should have a sheet named "Events" with columns:
timestamp, event_id, location, lat, lng, event_type, summary,
people_affected, severity_score, donation_links
"""

import os
import uuid
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any

import requests
import openai

try:
    import feedparser  # type: ignore
except ImportError:
    feedparser = None  # type: ignore

try:
    import praw  # type: ignore
except ImportError:
    praw = None  # type: ignore

try:
    # These imports are optional and may not be available during local tests.
    # The Google Cloud Storage client is used to archive JSON records when
    # running on GCP. The Sheets API client (googleapiclient) and
    # service account credentials are used to append rows to the Google Sheet.
    from google.cloud import storage  # type: ignore
    from google.oauth2 import service_account  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
except ImportError:
    # When running locally without these dependencies installed, the script
    # will still import successfully. Actual usage will fail without the
    # libraries, which is expected until deployed in the proper environment.
    storage = None  # type: ignore
    service_account = None  # type: ignore
    build = None  # type: ignore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configure logging to console for local execution with detailed output
if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)  # Set to DEBUG for maximum verbosity

# Read environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
OPENCAGE_API_KEY = os.environ.get("OPENCAGE_API_KEY")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

TWITTER_CONSUMER_KEY = os.environ.get("TWITTER_CONSUMER_KEY")
TWITTER_CONSUMER_SECRET = os.environ.get("TWITTER_CONSUMER_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

# RSS and social media monitoring configuration
RSS_FEED_URLS = os.environ.get("RSS_FEED_URLS", "").split(",") if os.environ.get("RSS_FEED_URLS") else []
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "HelpSignal:v1.0 (by /u/helpsignal)")
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN")

# Initialize OpenAI
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY


def fetch_news(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch recent news articles from NewsAPI.

    Args:
        limit: Maximum number of articles to fetch.

    Returns:
        A list of dictionaries with keys: title, description, url, published_at,
        and location (if available).
    """
    logger.info(f"Starting fetch_news with limit={limit}")
    articles: List[Dict[str, Any]] = []
    if not NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not provided; fetch_news will return an empty list.")
        return articles

    url = (
        "https://newsapi.org/v2/top-headlines?language=en&sortBy=publishedAt"
        f"&pageSize={limit}"
    )
    logger.debug(f"NewsAPI URL: {url}")
    headers = {"X-Api-Key": NEWS_API_KEY}
    try:
        logger.debug("Making request to NewsAPI...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"NewsAPI response status: {response.status_code}")
        logger.debug(f"NewsAPI returned {len(data.get('articles', []))} articles")
        for item in data.get("articles", []):
            articles.append(
                {
                    "title": item.get("title"),
                    "description": item.get("description") or "",
                    "url": item.get("url"),
                    "published_at": item.get("publishedAt"),
                    "location": extract_location(item.get("title", "") + " " + (item.get("description") or "")),
                }
            )
        logger.info(f"Successfully fetched {len(articles)} articles from NewsAPI")
    except Exception as exc:
        logger.error(f"Error fetching news: {exc}")
    logger.debug(f"fetch_news returning {len(articles)} articles")
    return articles


def fetch_rss_articles(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch recent articles from RSS feeds.

    Args:
        limit: Maximum number of articles to fetch per feed.

    Returns:
        A list of dictionaries with keys: title, description, url, published_at,
        location, and source.
    """
    logger.info(f"Starting fetch_rss_articles with limit={limit}")
    articles: List[Dict[str, Any]] = []
    if feedparser is None:
        logger.warning("feedparser not installed; RSS feeds will be skipped.")
        return articles
    
    if not RSS_FEED_URLS or RSS_FEED_URLS == [""]:
        logger.info("No RSS feed URLs configured.")
        return articles
    
    logger.debug(f"RSS feed URLs configured: {RSS_FEED_URLS}")
    
    for feed_url in RSS_FEED_URLS:
        feed_url = feed_url.strip()
        if not feed_url:
            continue
            
        try:
            logger.info(f"Fetching RSS feed: {feed_url}")
            feed = feedparser.parse(feed_url)
            logger.debug(f"RSS feed parsed, found {len(feed.entries)} entries")
            
            for entry in feed.entries[:limit]:
                # Extract publication date
                published_at = ""
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_at = datetime(*entry.published_parsed[:6]).isoformat()
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published_at = datetime(*entry.updated_parsed[:6]).isoformat()
                
                # Extract description/summary
                description = ""
                if hasattr(entry, 'summary'):
                    description = entry.summary
                elif hasattr(entry, 'description'):
                    description = entry.description
                
                articles.append({
                    "title": getattr(entry, 'title', ''),
                    "description": description,
                    "url": getattr(entry, 'link', ''),
                    "published_at": published_at,
                    "location": extract_location(getattr(entry, 'title', '') + " " + description),
                    "source": "RSS"
                })
            
            logger.info(f"Successfully processed {min(len(feed.entries), limit)} entries from {feed_url}")
                
        except Exception as exc:
            logger.error(f"Error fetching RSS feed {feed_url}: {exc}")
    
    logger.info(f"fetch_rss_articles returning {len(articles)} articles")
    
    return articles


def fetch_twitter_posts(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent Twitter posts related to humanitarian crises.

    Args:
        limit: Maximum number of posts to fetch.

    Returns:
        A list of dictionaries with keys: title, description, url, published_at,
        location, and source.
    """
    posts: List[Dict[str, Any]] = []
    if not TWITTER_BEARER_TOKEN:
        logger.info("Twitter Bearer Token not configured; skipping Twitter monitoring.")
        return posts
    
    # Crisis-related keywords and hashtags
    crisis_keywords = [
        "humanitarian crisis", "emergency relief", "disaster response",
        "refugee crisis", "natural disaster", "earthquake", "flood",
        "famine", "drought", "conflict", "war", "displacement"
    ]
    
    # Target accounts known for crisis reporting
    crisis_accounts = [
        "UN", "UNICEF", "WHO", "WFP", "refugees", "RedCross",
        "MSF_USA", "oxfam", "SavetheChildren", "CrisisGroup"
    ]
    
    headers = {
        "Authorization": f"Bearer {TWITTER_BEARER_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        # Search for crisis-related tweets
        query = " OR ".join([f'"{keyword}"' for keyword in crisis_keywords[:5]])  # Limit query length
        url = f"https://api.twitter.com/2/tweets/search/recent?query={query}&max_results={min(limit, 100)}&tweet.fields=created_at,author_id,public_metrics"
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "data" in data:
            for tweet in data["data"]:
                posts.append({
                    "title": tweet.get("text", "")[:100] + "..." if len(tweet.get("text", "")) > 100 else tweet.get("text", ""),
                    "description": tweet.get("text", ""),
                    "url": f"https://twitter.com/i/web/status/{tweet.get('id')}",
                    "published_at": tweet.get("created_at", ""),
                    "location": extract_location(tweet.get("text", "")),
                    "source": "Twitter"
                })
                
    except Exception as exc:
        logger.error(f"Error fetching Twitter posts: {exc}")
    
    return posts


def fetch_reddit_posts(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent Reddit posts from crisis-related subreddits.

    Args:
        limit: Maximum number of posts to fetch.

    Returns:
        A list of dictionaries with keys: title, description, url, published_at,
        location, and source.
    """
    posts: List[Dict[str, Any]] = []
    if praw is None:
        logger.warning("praw not installed; Reddit monitoring will be skipped.")
        return posts
    
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        logger.info("Reddit API credentials not configured; skipping Reddit monitoring.")
        return posts
    
    # Crisis-related subreddits
    crisis_subreddits = [
        "worldnews", "news", "globalhealth", "humanrights",
        "CrisisWatch", "ukraine", "syriancivilwar", "afghanistan",
        "refugees", "DisasterResponse", "HumanitarianAid"
    ]
    
    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT
        )
        
        posts_per_subreddit = max(1, limit // len(crisis_subreddits))
        
        for subreddit_name in crisis_subreddits:
            try:
                subreddit = reddit.subreddit(subreddit_name)
                
                # Get hot posts from the subreddit
                for submission in subreddit.hot(limit=posts_per_subreddit):
                    # Skip stickied posts
                    if submission.stickied:
                        continue
                    
                    # Convert Reddit timestamp to ISO format
                    published_at = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc).isoformat()
                    
                    # Use selftext if available, otherwise use title
                    description = submission.selftext if submission.selftext else submission.title
                    
                    posts.append({
                        "title": submission.title,
                        "description": description,
                        "url": f"https://reddit.com{submission.permalink}",
                        "published_at": published_at,
                        "location": extract_location(submission.title + " " + description),
                        "source": f"Reddit r/{subreddit_name}"
                    })
                    
            except Exception as exc:
                logger.error(f"Error fetching from subreddit {subreddit_name}: {exc}")
                continue
                
    except Exception as exc:
        logger.error(f"Error initializing Reddit client: {exc}")
    
    return posts


def extract_location(text: str) -> str:
    """Enhanced location extraction from text using regex patterns.

    Looks for common location patterns in crisis reporting.
    """


def classify_crisis(text: str) -> str:
    """Classify whether the text describes a humanitarian crisis.

    Uses the OpenAI ChatCompletion endpoint with the prompt defined in
    classify_crisis.yaml. Returns 'CRISIS' or 'NOT CRISIS'.
    """
    logger.debug(f"classify_crisis called with text: {text[:200]}...")
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set; defaulting classification to NOT CRISIS.")
        return "NOT CRISIS"
    messages = [
        {
            "role": "system",
            "content": (
                "You are a classifier that determines if a given news item or "
                "social media post describes a humanitarian crisis. A "
                "humanitarian crisis involves death, displacement, famine or "
                "other severe suffering. Output strictly either 'CRISIS' or "
                "'NOT CRISIS'. Do not include any additional commentary."
            ),
        },
        {"role": "user", "content": text},
    ]
    try:
        logger.debug("Making OpenAI classification request...")
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=5,
            temperature=0,
        )
        classification = resp.choices[0].message["content"].strip().upper()
        logger.debug(f"OpenAI classification response: {classification}")
        result = "CRISIS" if "CRISIS" in classification else "NOT CRISIS"
        logger.info(f"Classification result: {result}")
        return result
    except Exception as exc:
        logger.error(f"OpenAI classification error: {exc}")
        return "NOT CRISIS"


def estimate_impact(text: str) -> Tuple[int, int]:
    """Estimate the number of people affected and severity score from text.

    Returns a tuple of (people_affected, severity_score). On error, returns
    (0, 0).
    """
    logger.debug(f"estimate_impact called with text: {text[:200]}...")
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set; defaulting impact to 0,0.")
        return 0, 0
    messages = [
        {
            "role": "system",
            "content": (
                "You are an analyst that extracts the estimated number of people "
                "affected by a crisis and assigns a severity score. Consider the "
                "description and output an integer for 'People Affected' and an "
                "integer between 0 and 100 for 'Severity Score'. Severity 0 means "
                "negligible impact and 100 means catastrophic impact."
            ),
        },
        {"role": "user", "content": f"Description: {text}"},
    ]
    try:
        logger.debug("Making OpenAI impact estimation request...")
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=50,
            temperature=0,
        )
        content = resp.choices[0].message["content"].strip()
        logger.debug(f"OpenAI impact estimation response: {content}")
        people = 0
        severity = 0
        for line in content.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                if key.lower().strip().startswith("people"):
                    try:
                        people = int("".join(filter(str.isdigit, value)))
                    except ValueError:
                        people = 0
                elif key.lower().strip().startswith("severity"):
                    try:
                        severity = int("".join(filter(str.isdigit, value)))
                    except ValueError:
                        severity = 0
        logger.info(f"Impact estimation result: people_affected={people}, severity_score={severity}")
        return people, severity
    except Exception as exc:
        logger.error(f"OpenAI impact estimation error: {exc}")
        return 0, 0


def generate_summary(text: str) -> str:
    """Generate a 1–2 sentence summary of the crisis.

    Returns an empty string on failure.
    """
    logger.debug(f"generate_summary called with text: {text[:200]}...")
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set; defaulting summary to empty.")
        return ""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a writer tasked with producing a brief summary of a "
                "humanitarian crisis. Your summary should be one to two "
                "sentences, written in plain language. Be sure to mention the "
                "location, type of crisis and its human impact. Keep the tone "
                "clear and empathetic."
            ),
        },
        {"role": "user", "content": text},
    ]
    try:
        logger.debug("Making OpenAI summary generation request...")
        resp = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            max_tokens=100,
            temperature=0.7,
        )
        summary = resp.choices[0].message["content"].strip()
        logger.debug(f"OpenAI summary response: {summary}")
        logger.info(f"Generated summary: {summary}")
        return summary
    except Exception as exc:
        logger.error(f"OpenAI summary generation error: {exc}")
        return ""


def suggest_donations(event_type: str) -> List[str]:
    """Suggest donation organizations based on event type.

    Returns a list of organization names and URLs.
    """
    logger.debug(f"suggest_donations called with event_type: {event_type}")
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set; defaulting donation suggestions.")
        return ["https://www.directrelief.org/", "https://www.unhcr.org/"]
    messages = [
        {
            "role": "system",
            "content": (
                "You are a recommender for charitable organizations. Given the type "
                "of humanitarian crisis (e.g. war, famine, flood), suggest two or "
                "three well‑established and trustworthy organizations that accept "
                "donations for relief efforts. Provide their names and website URLs."
            ),
        },
        {"role": "user", "content": f"Event type: {event_type}"},
    ]
    try:
        logger.debug("Making OpenAI donation suggestion request...")
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=80,
            temperature=0,
        )
        content = resp.choices[0].message["content"].strip()
        logger.debug(f"OpenAI donation suggestion response: {content}")
        # Split by commas or newlines and filter out empty strings
        links = [item.strip() for item in content.replace("\n", ",").split(",") if item.strip()]
        logger.info(f"Donation suggestions: {links[:3]}")
        return links[:3]
    except Exception as exc:
        logger.error(f"OpenAI donation suggestion error: {exc}")
        return ["https://www.directrelief.org/", "https://www.unhcr.org/"]


def geocode(location: str) -> Tuple[float, float]:
    """Geocode a location string to latitude and longitude using OpenCage.

    Returns (0.0, 0.0) if geocoding fails.
    """
    logger.debug(f"geocode called with location: {location}")
    if not OPENCAGE_API_KEY or not location:
        logger.warning(f"Geocoding skipped - OPENCAGE_API_KEY: {'set' if OPENCAGE_API_KEY else 'not set'}, location: {location}")
        return 0.0, 0.0
    url = (
        "https://api.opencagedata.com/geocode/v1/json"
        f"?q={requests.utils.quote(location)}&key={OPENCAGE_API_KEY}&limit=1"
    )
    logger.debug(f"OpenCage geocoding URL: {url}")
    try:
        logger.debug("Making OpenCage geocoding request...")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"OpenCage response status: {response.status_code}")
        if data.get("results"):
            geometry = data["results"][0]["geometry"]
            lat, lng = geometry.get("lat", 0.0), geometry.get("lng", 0.0)
            logger.info(f"Geocoded '{location}' to lat={lat}, lng={lng}")
            return lat, lng
        else:
            logger.warning(f"No geocoding results found for location: {location}")
    except Exception as exc:
        logger.error(f"Geocoding error: {exc}")
    return 0.0, 0.0


def write_to_sheet(row: List[Any]) -> None:
    """Append a row to the Google Sheet.

    Expects GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID environment variables to
    be set. The row should be a list matching the sheet columns.
    """
    logger.info(f"write_to_sheet called with row data: {row}")
    if service_account is None or build is None:
        logger.warning("Google API client libraries not available; skipping sheet write.")
        return
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_SHEET_ID:
        logger.warning("Google Sheets credentials not configured; skipping sheet write.")
        logger.debug(f"GOOGLE_SERVICE_ACCOUNT_JSON: {'set' if GOOGLE_SERVICE_ACCOUNT_JSON else 'not set'}")
        logger.debug(f"GOOGLE_SHEET_ID: {'set' if GOOGLE_SHEET_ID else 'not set'}")
        return
    try:
        logger.debug(f"Loading service account credentials from: {GOOGLE_SERVICE_ACCOUNT_JSON}")
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        logger.debug("Building Google Sheets service...")
        service = build("sheets", "v4", credentials=creds)
        body = {"values": [row]}
        logger.debug(f"Appending to sheet ID: {GOOGLE_SHEET_ID}")
        logger.debug(f"Row data being written: {body}")
        service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="Events!A1",
            valueInputOption="RAW",
            body=body,
        ).execute()
        logger.info("Row appended to Google Sheet.")
    except Exception as exc:
        logger.error(f"Error writing to Google Sheet: {exc}")
        logger.debug(f"Full exception details: {exc}", exc_info=True)


def save_to_gcs(event_id: str, data: Dict[str, Any]) -> None:
    """Save a JSON record to Google Cloud Storage using a date partition scheme.

    Files are saved to gs://{GCS_BUCKET_NAME}/events/YYYY/MM/DD/event_id.json.
    The blob is made publicly readable so that the frontend can access it if
    necessary. The bucket should be configured to prevent listing.
    """
    logger.debug(f"save_to_gcs called with event_id: {event_id}")
    if storage is None:
        logger.warning("google-cloud-storage is not available; skipping GCS upload.")
        return
    if not GCS_BUCKET_NAME:
        logger.warning("GCS_BUCKET_NAME is not configured; skipping GCS upload.")
        return
    now = datetime.now(timezone.utc)
    key = f"events/{now:%Y}/{now:%m}/{now:%d}/{event_id}.json"
    logger.debug(f"GCS key: {key}")
    try:
        logger.debug("Creating GCS client...")
        client = storage.Client()  # uses default credentials from environment
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(key)
        logger.debug(f"Uploading JSON data to GCS: {json.dumps(data)[:200]}...")
        blob.upload_from_string(json.dumps(data), content_type="application/json")
        # Make the object publicly readable. If you prefer to control public
        # access via bucket IAM policies, remove the next line.
        blob.make_public()
        logger.info(f"Event archived to GCS at {key}")
    except Exception as exc:
        logger.error(f"Error uploading to GCS: {exc}")
        logger.debug(f"Full exception details: {exc}", exc_info=True)


def process_event(article: Dict[str, Any]) -> None:
    """Process a single news article and write results to storage.

    Args:
        article: A dictionary representing a news article.
    """
    logger.info(f"Processing article: {article.get('title', 'No title')}")
    logger.debug(f"Full article data: {article}")
    
    title = article.get("title", "")
    description = article.get("description", "")
    full_text = f"{title}\n\n{description}"
    logger.debug(f"Full text for processing: {full_text}")
    
    classification = classify_crisis(full_text)
    logger.info(f"Crisis classification: {classification}")
    if classification != "CRISIS":
        logger.info("Article not classified as crisis, skipping...")
        return

    people_affected, severity_score = estimate_impact(full_text)
    logger.info(f"Impact estimation: {people_affected} people affected, severity {severity_score}")
    
    summary = generate_summary(full_text)
    logger.info(f"Generated summary: {summary}")
    
    # If the article provided a location, use it; otherwise use a placeholder or
    # fallback extraction method.
    location = article.get("location") or "Unknown"
    logger.info(f"Location: {location}")
    
    lat, lng = geocode(location)
    logger.info(f"Geocoded coordinates: lat={lat}, lng={lng}")
    
    # Determine event type from keywords or categories; this is a simple heuristic.
    event_type = infer_event_type(full_text)
    logger.info(f"Inferred event type: {event_type}")
    
    donation_links = suggest_donations(event_type)
    logger.info(f"Donation links: {donation_links}")
    
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    logger.info(f"Generated event_id: {event_id}, timestamp: {timestamp}")
    
    # Compose row for Google Sheets
    row = [
        timestamp,
        event_id,
        location,
        lat,
        lng,
        event_type,
        summary,
        people_affected,
        severity_score,
        json.dumps(donation_links),
    ]
    logger.info(f"Composed row for Google Sheets: {row}")
    write_to_sheet(row)
    
    # Compose full event record for S3 archive
    event_record = {
        "timestamp": timestamp,
        "event_id": event_id,
        "location": location,
        "lat": lat,
        "lng": lng,
        "event_type": event_type,
        "title": title,
        "description": description,
        "summary": summary,
        "people_affected": people_affected,
        "severity_score": severity_score,
        "donation_links": donation_links,
        "source_url": article.get("url"),
    }
    logger.debug(f"Event record for GCS: {event_record}")
    save_to_gcs(event_id, event_record)
    
    # Optionally tweet
    try:
        logger.debug("Attempting to tweet crisis...")
        tweet_crisis(event_record)
    except Exception as exc:
        logger.error(f"Error tweeting crisis: {exc}")
    
    logger.info(f"Finished processing article: {title}")


def infer_event_type(text: str) -> str:
    """Simple heuristic to infer event type from text.

    This implementation checks for keywords; for more robust classification,
    consider using a fine‑tuned model or more complex NLP techniques.
    """
    lower = text.lower()
    if any(k in lower for k in ["war", "conflict", "battle"]):
        return "War"
    if any(k in lower for k in ["famine", "hunger", "starvation"]):
        return "Famine"
    if any(k in lower for k in ["flood", "storm", "hurricane", "typhoon"]):
        return "Flood"
    if any(k in lower for k in ["earthquake", "quake"]):
        return "Earthquake"
    if any(k in lower for k in ["drought"]):
        return "Drought"
    return "Other"


def tweet_crisis(event: Dict[str, Any]) -> None:
    """Post a tweet about the crisis.

    Uses the environment variables for Twitter keys and tokens. Requires
    tweepy to be installed. If credentials are missing, the tweet is skipped.
    """
    if not all([
        TWITTER_CONSUMER_KEY,
        TWITTER_CONSUMER_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET,
    ]):
        logger.info("Twitter credentials not configured; skipping tweet.")
        return
    try:
        import tweepy  # type: ignore

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
        logger.info("Tweet posted about crisis.")
    except Exception as exc:
        logger.error(f"Twitter posting error: {exc}")


def main(request=None) -> str:
    """Entry point for the Cloud Function.

    Google Cloud Functions pass a Flask request object when triggered via HTTP.
    For Cloud Scheduler triggers, request will be None.
    """
    logger.info("HelpSignal backend invoked")
    logger.debug("Starting main function execution")
    
    # Collect articles from all sources
    all_articles = []
    
    # Fetch from NewsAPI if available
    if NEWS_API_KEY:
        logger.info("Fetching articles from NewsAPI...")
        news_articles = fetch_news(limit=15)
        all_articles.extend(news_articles)
        logger.info(f"Fetched {len(news_articles)} articles from NewsAPI")
    else:
        logger.info("NewsAPI key not configured, skipping NewsAPI")
    
    # Fetch from RSS feeds
    logger.info("Fetching articles from RSS feeds...")
    rss_articles = fetch_rss_articles(limit=10)
    all_articles.extend(rss_articles)
    logger.info(f"Fetched {len(rss_articles)} articles from RSS feeds")
    
    # Fetch from Twitter
    logger.info("Fetching posts from Twitter...")
    twitter_posts = fetch_twitter_posts(limit=15)
    all_articles.extend(twitter_posts)
    logger.info(f"Fetched {len(twitter_posts)} posts from Twitter")
    
    # Fetch from Reddit
    logger.info("Fetching posts from Reddit...")
    reddit_posts = fetch_reddit_posts(limit=15)
    all_articles.extend(reddit_posts)
    logger.info(f"Fetched {len(reddit_posts)} posts from Reddit")
    
    logger.info(f"Total articles/posts collected: {len(all_articles)}")
    
    if not all_articles:
        logger.warning("No articles collected from any source!")
        return "OK - No articles to process"
    
    # Process each article/post
    processed_count = 0
    crisis_count = 0
    for article in all_articles:
        try:
            logger.info(f"Processing article {processed_count + 1}/{len(all_articles)}")
            process_event(article)
            processed_count += 1
        except Exception as exc:
            logger.error(f"Error processing event: {exc}")
            logger.debug(f"Full exception details: {exc}", exc_info=True)
    
    logger.info(f"Processing complete. Processed {processed_count} articles")
    logger.info("HelpSignal backend execution finished")
    
    return "OK"


if __name__ == "__main__":
    # For local debugging, call main() directly.
    print(main())