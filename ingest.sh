#!/bin/bash
# cd into the directory of the script
cd "$(dirname "$0")" || exit
if [[ -z "${ACTIVATE_CONDA}" ]]; then
  /home/ubuntu/miniconda3/bin/conda activate kapidev
fi


pip install -r requirements.txt -U
pip install -r dev-requirements.txt -U

#Videos from Program Pages (links)
python kadist_videos.py
#python external_videos.py
#60 Second Interviews from People Pages (links)
python kview_videos.py
python download_optimized.py
