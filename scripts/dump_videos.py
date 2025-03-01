#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json

from lib.app_utils import load_videos

if __name__ == "__main__":
    kvl, interviews, external_videos = load_videos(
        manifest_folder="storage/imported_videos", suppress_image_data_uri=True
    )

    for video in interviews + kvl + external_videos:
        print(json.dumps(video, indent=2, ensure_ascii=False))
