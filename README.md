# HelpSignal

HelpSignal is a full‑stack system that monitors news sources in real time, uses
AI to detect humanitarian crises, summarises each event, estimates the human
impact, recommends vetted charities and visualises the results on an
interactive map. The backend periodically scans news feeds and archives
structured data, while the frontend displays live events and links users to
organisations that can help.

## Features

### Backend

* **Automated ingestion** – fetches news articles on a schedule via NewsAPI or RSS feeds.
* **Multi-source monitoring** – supports NewsAPI, RSS feeds, Twitter/X, and Reddit for comprehensive crisis detection.
* **AI classification** – uses GPT‑3.5 to classify whether a news item describes a humanitarian crisis.
* **Impact estimation** – uses GPT‑3.5 to extract an approximate number of people affected and a severity score (0–100).
* **Summary generation** – uses GPT‑4 to generate a concise, human‑readable summary (1–2 sentences).
* **Donation suggestions** – uses GPT‑3.5 to recommend two or three well‑established aid organisations.
* **Geocoding** – turns location names into latitude/longitude via OpenCage.
* **Data storage** – appends a structured row to a Google Sheet for dashboard consumption and archives a full JSON record to a Google Cloud Storage bucket.
* **Optional tweeting** – posts a brief alert to Twitter/X when a new crisis is detected.

### Frontend

* **Interactive map** – built with Mapbox GL JS to display crisis locations with markers coloured by severity.
* **Filters** – filter events by type and minimum severity; view safe zones (less severe events).
* **Details panel** – click a marker to view the summary, people affected, severity and donation links.
* **How to Help button** – one‑click access to donation sites.

## Architecture

The system consists of loosely coupled components communicating via cloud
services. A high‑level view:

```
+----------------------+       +------------------------+       +--------------------+
|  News Sources / RSS |       |  Cloud Scheduler (GCP) |       |     Twitter/X     |
|      or NewsAPI     |  -->  |   triggers Cloud       |  -->  | (optional tweets) |
+----------------------+       |   Function every 5 min |       +--------------------+
                               +------------------------+
                                       |
                                       v
                               +------------------------+
                               |  Cloud Function (main) |
                               |  - fetches articles    |
                               |  - calls OpenAI (GPT)  |
                               |  - geocodes location   |
                               |  - writes to Sheets    |
                               |  - uploads to GCS      |
                               +------------------------+
                                       |
                               +------------------------+
                               |  Google Sheet (Events) |
                               +------------------------+
                                       |
                                       v
                               +------------------------+
                               | Frontend (Mapbox GL)   |
                               |  hosted via GitHub     |
                               |  Pages or Cloud Storage |
                               +------------------------+
```

## Setup

### 1. Prepare your accounts

1. **OpenAI** – Obtain an API key with access to GPT‑3.5 and GPT‑4. Create an
   account at [OpenAI Platform](https://platform.openai.com) and generate a new key.
2. **NewsAPI (optional)** – Create an account at [NewsAPI](https://newsapi.org) and get an API key.
3. **Twitter/X (optional)** – Create a developer account at [Twitter Developer Portal](https://developer.twitter.com) and obtain a Bearer Token for API v2 access.
4. **Reddit (optional)** – Create a Reddit application at [Reddit Apps](https://www.reddit.com/prefs/apps) and obtain client ID and secret.
5. **Google Cloud** – Create a new GCP project. Enable **Cloud Functions**,
   **Sheets API**, **IAM**, and **Cloud Scheduler**. Create a service account with
   the _Service Account Token Creator_ role and download the `credentials.json`
   file. Note the service account email – you will need to share the Google
   Sheet with it.
6. **Google Sheets** – Create a sheet named `HelpSignalEvents` and add a sheet
   tab called `Events`. Add the following header row in row 1:

   | timestamp | event_id | location | lat | lng | event_type | summary | people_affected | severity_score | donation_links |
   |----------|---------|----------|----|----|-----------|---------|-----------------|--------------|----------------|

   Share the sheet with **edit** permission to your GCP service account email. In the
   **File > Share** dialog, click **Copy link** and change it to **Anyone with the
   link – Viewer**. Record the Sheet ID from the URL.
7. **Google Cloud Storage** – Within your GCP project, create a Cloud Storage
   bucket named `helpsignal-archive` (or another name of your choice). This
   bucket will store the archived JSON records. Use the helper script
   [`infra/gcs_setup_commands.sh`](infra/gcs_setup_commands.sh) or the
   Cloud Console to configure public read access on individual objects while
   preventing directory listing. Because the backend runs as a Cloud
   Function, it will automatically authenticate to GCS using the service
   account credentials; no additional access keys are required.
8. **Mapbox** – Create a free account at https://www.mapbox.com and obtain a
   Mapbox access token.

### 2. Configure environment

Copy `.env.template` to `.env` in the repo root:

```sh
cp .env.template .env
```

Open `.env` and populate each variable with your own secrets:

```ini
OPENAI_API_KEY=sk-...
NEWS_API_KEY=...
OPENCAGE_API_KEY=...
GOOGLE_SHEET_ID=...
GOOGLE_SERVICE_ACCOUNT_JSON=/absolute/path/to/credentials.json
GCS_BUCKET_NAME=helpsignal-archive
TWITTER_CONSUMER_KEY=...
TWITTER_CONSUMER_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_TOKEN_SECRET=...
TWITTER_BEARER_TOKEN=...
RSS_FEED_URLS=https://feeds.reuters.com/reuters/topNews,https://rss.cnn.com/rss/edition.rss
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=HelpSignal:v1.0 (by /u/yourusername)
MAPBOX_TOKEN=...
FUNCTION_SERVICE_ACCOUNT=your-service-account@your-project.iam.gserviceaccount.com
```

**Important:** Never commit your `.env` file or `credentials.json` to version
control. Use Google Secret Manager or another secret vault for production.

### 3. Deploy the backend

Install the GCP SDK and authenticate:

```sh
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID
```

Enable necessary APIs:

```sh
gcloud services enable cloudfunctions.googleapis.com sheets.googleapis.com iamcredentials.googleapis.com cloudscheduler.googleapis.com
```

Create a Cloud Scheduler job to trigger the function every 5 minutes:

```sh
gcloud scheduler jobs create http helpsignal-cron \
  --schedule="*/5 * * * *" \
  --http-method=GET \
  --uri="https://REGION-PROJECT_ID.cloudfunctions.net/helpsignal-backend"
```

Deploy the Cloud Function:

```sh
cd infra
./gcp_function_deploy.sh
```

The script reads variables from `.env` and deploys the function from
`scripts/main.py`. Adjust the `FUNCTION_NAME`, `REGION` and other options at the
top of the script as needed.

### 4. Deploy the frontend

The frontend is a static site in the `frontend` directory. You can host it
via GitHub Pages or any static hosting platform. To deploy to GitHub Pages
using the included script:

```sh
cd infra
./github_pages_deploy.sh
```

Ensure that your repository has a remote named `origin` and that GitHub Pages
is configured to serve the `gh-pages` branch. The script commits any
outstanding changes in the `frontend` folder and pushes it as a subtree.

Alternatively, you can upload the contents of `frontend` to a Cloud Storage bucket with
static website hosting enabled (see `infra/gcs_setup_commands.sh` for bucket configuration).

### 5. Confirm everything is working

1. Wait a few minutes after deployment. The Cloud Function should start
   ingesting news and populating the Google Sheet.
2. Open the sheet and verify that new rows appear with crisis data.
3. Visit the deployed frontend. The map should show markers; click one to see
   details and donation links.
4. (Optional) Check your Twitter account for crisis alerts.

## Contributing

Pull requests and issues are welcome! If you have ideas for additional
filters, visualisations or integrations (e.g. geotagged tweets, mobile PWA,
analytics dashboard), feel free to open an issue or submit a PR. When
contributing code, please follow the existing project structure and include
tests where appropriate.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file
for details.