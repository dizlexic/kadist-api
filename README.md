# Kadist TV

A repository for ingesting and managing Kadist TV media.

---

## Development Setup

### 1. Create and Activate Conda Environment

```bash
$ conda create -n kadisttv python=3.8
$ conda activate kadisttv
```

### 2. Install Requirements

```bash
$ pip install -r requirements.txt
$ pip install -r dev-requirements.txt
```

### 3. Configure Environment Variables

Copy the `.env.example` file to `.env` and fill in the required values:

```plaintext
AWS_ACCESS_KEY_ID="<your-aws-access-key-id>"
AWS_SECRET_ACCESS_KEY="<your-aws-secret-access-key>"
```

---

## Admin Dashboard

Access the admin UI at the following URL path:

`/admin`

---

## Clip Overrides

Specify clip overrides using the `config_files/clip_overrides.json` file. The format should be as follows:

```json
{
  "video_id": {
    "clip_offset": 12,
    "clip_length": 42
  }
}
```

`clip_offset` and `clip_length` are optional fields. Adjust these values as needed.

---

## Import Pipeline

### Ingest

Run the ingestion script manually or set it as a cron job:

```bash
$ ./bin/ingest.sh
```

### Run the Server

Start the server locally:

```bash
$ ./bin/server.sh
```

---

## TODO (Feature Backlog)

- [ ] Add a `scrape_vimeo.py` script to scrape Vimeo videos.
- [ ] Extract video poster links for KViews.
- [ ] Scrape metadata from:
  - Vimeo: [https://vimeo.com/kadist](https://vimeo.com/kadist)
  - YouTube: [https://www.youtube.com/user/KADIVIEW/videos](https://www.youtube.com/user/KADIVIEW/videos)
- [ ] Generate `config_files/vimeo_videos.json` with the following format:
  ```json
  [
    {
      "permalink": "http://example.com/abraham-cruzvillegas/",
      "title": "Abraham Cruzvillegas",
      "region": "All",
      "description": "Description of the video...",
      "image_url": "https://example.com/image.png",
      "image_width": 350,
      "image_height": 218,
      "video_url": "http://example.com/video.mp4"
    }
  ]
  ```
- [ ] Use the existing pipeline to fetch, clip, and transcode videos.

---

## Notes

Refer to `kview_videos.py` for the scraping logic. To scrape Vimeo videos:

- Create a new script: `vimeo_videos.py`.
- Mimic the structure of the `scrape_videos()` function.
- Ensure the output JSON is placed in `config_files/vimeo_videos.json`.
- The pipeline to fetch and transcode uses [yt_dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

Keep the existing fetching and transcoding mechanisms unchanged to ensure system compatibility.