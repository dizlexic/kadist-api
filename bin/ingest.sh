#!/usr/bin/env bash
# cd into the directory of the script
cd "$(dirname "$0")/../" || exit

eval "$(conda shell.bash hook)"
conda activate ktv-api

PYTHONPATH=. python scripts/pipeline/kadist_videos.py
PYTHONPATH=. python scripts/pipeline/external_videos.py
PYTHONPATH=. python scripts/pipeline/kview_videos.py
PYTHONPATH=. python scripts/pipeline/download_optimized.py
