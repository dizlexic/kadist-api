# Kadist TV

A repository for ingesting and managing Kadist TV media.

---

## Requirements

- Python 3.12+ or [Conda](https://docs.conda.io/projects/conda/en/stable/)
- [FFmpeg](https://www.ffmpeg.org/)

## Development Setup

Follow these steps to set up the development environment:

### Using Conda Environment

#### 1. Create a Conda Environment

Recommended: Create a new Conda using the provided `environment.yml` file:

```shell script
$ conda env create -f environment.yml
$ conda activate ktv-api
```

Alternatively, create a new Conda environment manually:

```shell script
$ conda create -n kadisttv python=3.12.9
$ conda activate kadisttv
```

Make sure to activate the environment before proceeding.

#### 2. Install Requirements

If not using `environment.yml`, manually install dependencies:

```shell script
$ pip install -r requirements.txt
$ pip install -r dev-requirements.txt
```

#### 3. Configure Environment Variables

Copy the provided `.env.example` file to `.env` and set appropriate values for required variables:

```
AWS_ACCESS_KEY_ID="<your-aws-access-key-id>"
AWS_SECRET_ACCESS_KEY="<your-aws-secret-access-key>"
```

---

## Directory Structure

Understanding the project directory structure is critical for seamless operation:

- **`bin/`**  
  Contains scripts for running key operations such as ingestion pipeline and server startup.
  - `ingest.sh`: Runs the ingestion pipeline to fetch, clip, and process media.
  - `server.sh`: Launches the application server for local testing and development.

- **`storage/`**  
  Group for all storage-related files. This includes:
  - `storage/tmp/`: Holds raw media files before processing.
  - `storage/caches/`: sqlite databases for caching metadata and other information.
  - `storage/config/`: Holds configuration files for the application.  
    Example:
    - `clip_overrides.json`: Defines custom specifications for clips, such as offsets and lengths.
  - `imported_videos/`: Directory for storing videos that have been ingested into the system.
- **`lib/`**  
  Contains the core library files for the application.

- **`scripts/`**
  Contains scripts for various tasks, including ingestion and processing of media files.
  - `scripts/pipeline/*`: Contains the pipeline scripts for processing media files.

- **`tests`**
  - Contains optimism.

- **`views/`**
  - Contains HTML templates for the web application.

  - **`requirements.txt`**  
    Specifies Python dependencies required for the project.

  - **`dev-requirements.txt`**  
    Contains additional dependencies for development and testing purposes.

---

## How to Use

### Ingest Media

To ingest new media into the system, use the ingestion script. This script will fetch video data, apply overrides from
configuration files (if any), and process the media:

```shell script
$ ./bin/ingest.sh
```

To continually ingest media, set up a cron job or task scheduler to run the script at regular intervals.
example cron job:

```shell script
* */5 * * * /path/to/ktv-api/bin/ingest.sh
```

This cron job will run the ingestion pipeline every 5 hours.

---

### Start the Server

To access the application, start the local server using:

```shell script
$ ./bin/server.sh
```

Once the server starts, you can access the admin dashboard at:

`http://localhost:<API_PORT>/admin`

Replace `<API_PORT>` with the port number specified in your `.env` file (default is 1337).

---

## Clip Overrides

Custom clip configurations can be specified in `config_files/clip_overrides.json`. Override the clip properties for any
video using the following format:

```json
{
  "video_id": {
    "clip_offset": 12,
    "clip_length": 42
  }
}
```

- `clip_offset`: Time (in seconds) to start the clip (optional).
- `clip_length`: Duration (in seconds) of the clip (optional).

If unspecified, default pipeline values are used.

---

## Notes

- Ensure that all environment variables are set correctly in the `.env` file before running the application.
- For any issues or feature requests, please open an issue in the repository.
- Use cron jobs or task schedulers to automate the ingestion process if needed.
- The application stores all imported video data in the `storage/imported_videos/` directory.
-
Consider [setting up a service](https://stackoverflow.com/questions/38739198/how-to-run-a-script-as-a-service-in-ubuntu)
to monitor the application and restart it if it crashes.

---
