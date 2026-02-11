# Kadist TV - Knowledge Transfer Documentation

## Project Overview
Kadist TV is a video aggregation and search API. It collects video metadata and media from multiple Kadist-related sources, processes them into a unified format, and serves them via a Flask-based REST API.

### Core Components
1.  **Ingestion Pipeline**: A series of scripts that scrape metadata, download videos, upload to S3, and generate manifests.
2.  **API Server**: A Flask application that serves video data and provides search capabilities.
3.  **Search Engine**: Powered by `Whoosh`, it indexes video manifests for full-text search.
4.  **Storage Layout**:
    -   `storage/config/`: Source configuration and scraped metadata.
    -   `storage/imported_videos/`: Individual JSON manifests (one per video). This is the "database" for the API.
    -   `storage/caches/`: SQLite databases for caching network requests and poster images.
    -   `storage/tmp/`: Temporary workspace for video processing.
    -   `S3 Bucket`: Remote storage for full MP4 files and generated 20s preview clips.

---

## Ingestion Pipeline (`bin/ingest.sh`)

The pipeline is the primary way data enters the system. It is designed to be idempotent and efficient.

### Step 1: `scripts/pipeline/kadist_videos.py`
-   **Purpose**: Scrapes the main Kadist website (`kadist.org`) for program and interview videos.
-   **Action**: Iterates through regional pages, identifies Vimeo embeds, and resolves them to raw MP4 links.
-   **Output**: `storage/config/kadist_videos.json`.

### Step 2: `scripts/pipeline/external_videos.py`
-   **Purpose**: Processes external video entries defined in a CSV export.
-   **Action**: Reads `KADIST-Export.csv`, scrapes metadata (title, description, tags, images) from the corresponding WordPress pages.
-   **Output**: `storage/config/external_videos.json`.

### Step 3: `scripts/pipeline/kview_videos.py`
-   **Purpose**: Scrapes "60 Seconds" video series.
-   **Action**: Reads URLs from `storage/config/kview_scrape_pages.yaml` and extracts video/image metadata.
-   **Output**: `storage/config/kview_videos.json`.

### Step 4: `scripts/pipeline/download_optimized.py`
This is the core engine of the pipeline. It implements the **Individual Processing Strategy**, replacing older methods that attempted to download all videos before processing.

**How it works for each video source (KVL, Kadist, External, KView):**
1.  **ID Generation**: Creates a unique MD5 hash based on the video URL.
2.  **S3 Check**: Checks if the video (`<ID>.mp4`) already exists in the S3 bucket.
3.  **Download & Upload**:
    -   If missing from S3, it downloads the video locally to `storage/tmp/`.
    -   Uses `ffmpeg` for direct links or `yt-dlp` for YouTube/Vimeo.
    -   Uploads the resulting MP4 to S3.
4.  **Clip Generation**:
    -   Generates a 20-second preview clip (`<ID>_clip_20s.mp4`) using `ffmpeg`.
    -   Uploads the clip to S3.
5.  **Metadata Enrichment**:
    -   Detects video duration via `ffprobe`.
    -   Generates tags using the `yake` keyword extractor.
    -   Generates a base64 `image_data_uri` for the poster image (enables instant loading in the UI).
6.  **Manifest Creation**: Writes a final JSON manifest to `storage/imported_videos/<ID>.json`.
7.  **Cleanup**: Deletes local temporary files from `storage/tmp/` after processing.

*Note: `fetch_kvl` in this script also pulls data from an external API (`arpedia.herokuapp.com`).*

---

## API Server (`app.py`)

The server is optimized for fast startup and low-latency responses.

### Initialization
-   **Video Loading**: At startup, `load_videos()` scans `storage/imported_videos/` and loads all JSON manifests into memory.
-   **Search Indexing**: The `Whoosh` search engine initializes an in-memory index from these manifests.
-   **Categorization**: Videos are categorized by `type` (kvl, interview, external, kview).

### Key Endpoints
-   `/ui`: The main user interface (renders `templates/ui.html`).
-   `/ktv_api/all_videos`: Returns the full library of videos.
-   `/ktv_api/suggested_videos`: Uses a combination of pinned videos (from S3 `pinned.json`), popularity (watch stats from S3 `stats.json`), and random selection.
-   `/ktv_api/search`: Full-text search endpoint.
-   `/admin`: Dashboard for pinning videos and viewing watch statistics.

---

## Data Utilities (`lib/`)
-   `app_utils.py`: Contains core logic for loading manifests, managing pinned videos, and calculating popularity.
-   `dev_utils.py`: Utilities for image-to-base64 conversion and generic file downloads.
-   `s3helper.py`: A wrapper around `boto3` for S3 interactions.
-   `search_engine.py`: Encapsulates the `Whoosh` indexing and querying logic.

---

## Deprecation & Cleanup Candidates

The following files are no longer part of the active ingestion pipeline and can likely be deprecated:

1.  **`scripts/download_videos.py`**: Superseded by `scripts/pipeline/download_optimized.py`.
2.  **`scripts/import_csv.py`**: Redundant scraping logic; functionality is now handled by `scripts/pipeline/external_videos.py`.
3.  **`scripts/dump_videos.py`**: Legacy script for dumping video data.
4.  **`storage/config/kadist_videos.json.old`**: Backup file that can be removed.
5.  **`storage/imported_videos/`**: Any JSON in this folder, whose video URL is no longer in the source configs will persist but can be safely removed if a full library refresh is desired.

---

## Development Workflow

1.  **Configuration**: Set environment variables in `.env` (S3 bucket, AWS keys, etc.).
2.  **Ingestion**: Run `./bin/ingest.sh` to refresh the library and update S3.
3.  **Serving**: Run `./bin/server.sh` to start the Flask API.
4.  **UI Development**: The UI is a single-page template (`templates/ui.html`) that communicates with the API endpoints.
