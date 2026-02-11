### Kadist API — Development Guidelines

#### Build and Configuration

- Python version: 3.12.x. Preferred workflow is via Conda using `environment.yml`.
    - Create env: `conda env create -f environment.yml && conda activate ktv-api`
    - Or use system Python and install: `pip install -r requirements.txt -r dev-requirements.txt`

- Required native tools: FFmpeg must be available in PATH for media workflows referenced by scripts.

- Environment variables: Copy `.env.example` to `.env` and set required secrets if you plan to run ingestion or
  S3‑backed features. At minimum for S3:
    - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
    - The S3 bucket used by the app utilities is currently hard‑coded as `arpedia-dev` in `lib/app_utils.py` via
      `S3Helper("arpedia-dev")`. If you need a different bucket for local/dev, adjust `S3Helper` initialization or
      provide a compatible bucket with the expected keys: `pinned.json`, `stats.json`.

- Data layout expectations:
    - Local manifests live under `storage/imported_videos/*.json`. Many workflows (e.g., `load_videos` and
      `SearchEngine` debug helpers) read from there. Keep sample JSONs to enable local runs and tests without network
      calls.
    - Caches/SQLite under `storage/caches/`, temp media under `storage/tmp/`.

- Running the ingestion pipeline and server: see `README.md` for `./bin/ingest.sh` and `./bin/server.sh`. The server
  exposes an admin UI at `http://localhost:<API_PORT>/admin` (default port 1337).

- Third‑party package quirk (YouTubeSearchPython):
    - Until upstream is fixed, you must disable proxies in `youtubesearchpython/core/requests.py` by commenting out
      `proxies=self.proxy` in the `httpx.post(...)` call. This hack is documented in `README.md` under “MASSIVE HACK”.
      If you vendor or fork the package, remove the proxy argument instead of editing site‑packages in place.

#### Testing

- Framework: The repo does not currently depend on `pytest`; use Python’s built‑in `unittest` for quick checks and
  CI‑free validation. You can still add `pytest` locally if you prefer, but keep `unittest` compatibility for
  portability.

- Running tests:
    - Standard discovery from the project root:
        - `python -m unittest` (runs discovery using defaults)
        - or `python -m unittest discover -s tests -p "test_*.py"`

- Adding tests:
    - Place files under `tests/` named `test_*.py`.
    - Favor unit tests that do not require network or AWS. Use the sample JSONs in `storage/imported_videos/` and pure
      functions in `lib/`.
    - For code paths that touch S3, prefer testing against small in‑memory inputs and mock `S3Helper` behavior rather
      than hitting AWS. If you must hit AWS, ensure you configure credentials and use a non‑prod bucket.

- Example test (verified locally during preparation of these guidelines):
    - Purpose: validate that `filter_tags` removes stop words and enforces minimum term frequency and character
      constraints.
    - Create a file `tests/test_smoke.py` with:
      ```python
      import unittest
      from lib.app_utils import filter_tags
  
      class TestFilterTags(unittest.TestCase):
          def test_basic_filtering(self):
              videos = [
                  {"tags": ["Art", "Kadist", "artist", "video", "Cinema", "cinema", "cinema", "2024", "ok"]},
                  {"tags": ["Cinema", "theory", "cinema", "ok"]},
              ]
  
              # min_tf=2 will keep tags appearing at least twice across videos
              filter_tags(videos, min_tf=2)
  
              # Stop words removed; lowercase numeric-only filtered; only alnum lowercase words persist
              kept = sorted(set(tag for v in videos for tag in v["tags"]))
              self.assertIn("cinema", kept)
              self.assertIn("ok", kept)  # appears twice across items
              self.assertNotIn("Art", kept)
              self.assertNotIn("artist", kept)
              self.assertNotIn("video", kept)
              self.assertNotIn("Kadist", kept)
              self.assertNotIn("2024", kept)  # numeric only is rejected by the pattern
  
      if __name__ == "__main__":
          unittest.main()
      ```
    - Run it: `python -m unittest tests/test_smoke.py -v`
    - Expected: tests pass. After validating locally, you can remove the file or keep it as a starter test.

Notes on data‑dependent tests:

- Functions like `load_videos` traverse `storage/imported_videos/*.json` and by default strip `image_data_uri`. If you
  write tests around search, prefer a tiny fixture JSON placed in that directory or inject documents directly into
  `SearchEngine` using a Whoosh `Schema` to avoid filesystem coupling.

#### Development Conventions and Debugging Tips

- Style/tooling:
    - The repo includes `black` and `flake8` in `dev-requirements.txt`. Use them locally: `black .` and `flake8`.
    - Keep import style consistent with existing modules (standard libs first, third‑party, then local `lib.*`).

- Search debugging:
    - `lib/search_engine.py` has a `__main__` block that builds an in‑memory Whoosh index from manifests and prints
      results for a hard‑coded query. You can run it directly for diagnostics: `python -m lib.search_engine`. Adjust the
      query and analyzer if needed.

- S3 interactions:
    - `lib/app_utils.py` persists simple JSON lists to S3 keys `pinned.json` and `stats.json` via `S3Helper`. For
      offline/dev work, stub `S3Helper` or swap it for a local FS implementation to avoid network dependencies.

- Pipelines and long‑running jobs:
    - See `scripts/` and `bin/` for operational entry points. If you schedule ingestion, prefer a cron or a supervised
      service. Keep an eye on `storage/tmp/` growth and clean it periodically.
