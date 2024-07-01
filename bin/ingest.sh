#!/usr/bin/env bash
# cd into the directory of the script
cd "$(dirname "$0")/../" || exit

eval "$(conda shell.bash hook)"
conda activate ktv-api

pip install -r requirements.txt -U
pip install -r dev-requirements.txt -U

python kadist_videos.py
python external_videos.py
python kview_videos.py
python download_optimized.py
