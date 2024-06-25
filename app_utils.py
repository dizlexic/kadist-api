import os
from typing import Dict, List, Sequence

import glob
import json
import re
import random
import time
import datetime


from collections import Counter, defaultdict


from s3helper import S3Helper

s3 = S3Helper("arpedia-dev")

#
# Pinning - these videos are always in the suggested list
#

pinned_file = "pinned.json"


def get_pinned_videos():
    pinned = s3.read_json(pinned_file) or []
    return pinned


def add_pin_video(video_id: str):
    pinned = s3.read_json(pinned_file) or []
    if video_id not in pinned:
        pinned.append(video_id)
        s3.write_json(pinned_file, pinned)
        return pinned


def remove_pin_video(video_id: str):
    pinned = s3.read_json(pinned_file) or []
    if video_id in pinned:
        pinned.remove(video_id)
        s3.write_json(pinned_file, pinned)
        return pinned


stats_file = "stats.json"

#
# stats are stored on S3 as a list of dicts, each dict contains
# the date the video was watched, the video record
#
#


def increment_popularity(video_id: str) -> Dict:

    stats = s3.read_json(stats_file) or []

    stats.append({"video_id": video_id, "epoch_s": time.time()})

    s3.write_json(stats_file, stats)

    return sum(1 for x in stats if x["video_id"] == video_id)


def get_popularity() -> Dict[str, int]:
    stats = s3.read_json(stats_file) or []

    now_dt = datetime.datetime.fromtimestamp(time.time())

    d = defaultdict(int)
    for stat in stats:
        delta = now_dt - datetime.datetime.fromtimestamp(stat["epoch_s"])

        score = 1 if delta.days < 30 else 0.5

        d[stat["video_id"]] += score

    return dict(d)


def filter_tags(videos: Sequence[Dict], min_tf: int = 1):
    stop_tags = frozenset(["art", "artist", "kadist", "arte", "video"])

    c = Counter([tag.lower() for video in videos for tag in video["tags"]])

    pattern = re.compile("[a-z0-9]+")

    for video in videos:
        video["tags"] = list(
            {
                tag
                for tag in video["tags"]
                if c[tag.lower()] > min_tf
                and tag.lower() not in stop_tags
                and pattern.fullmatch(tag.lower())
            }
        )


def _remove_image_data_uri(d: Dict) -> Dict:
    return {k: v for k, v in d.items() if k not in ["image_data_uri"]}


def load_videos(
    manifest_folder, suppress_image_data_uri: bool = True
) -> List[List[dict]]:

    videos = []

    for fname in glob.glob(f"{manifest_folder}/*.json"):
        print("** attempting to load:", fname)
        j = json.loads(open(fname).read())
        video = _remove_image_data_uri(j) if suppress_image_data_uri else j
        extended_video = _extend_info(video)
        videos.append(extended_video)

    kvl = [video for video in videos if video["type"] == "kvl"]
    interviews = [video for video in videos if video["type"] == "interview"]
    external_videos = [video for video in videos if video["type"] == "external"]
    kview_videos = [video for video in videos if video["type"] == "kview"]

    filter_tags(kvl + interviews + external_videos + kview_videos)

    print(
        f" * kvl: {len(kvl)}, interviews: {len(interviews)}, external: {len(external_videos)}, kview: {len(kview_videos)}"
    )
    return [kvl, interviews, external_videos, kview_videos]

def suggested_videos(
        video_index: List[Dict],
        interview_videos: List[Dict],
        kvl_videos: List[Dict],
        external_videos: List[Dict],
        kview_videos: List[Dict],
        count: int,
) -> List[Dict]:

    videos = []

    #
    # pinned first
    #
    for video_id in get_pinned_videos():
        if video_id in video_index:
            video = video_index[video_id]
            print(
                f" * suggesting (based on being pinned), title: [{video['title']}]",
            )
            videos.append(video)

    togo = int(max(count - len(videos), 0) * 0.75)

    if togo:
        #
        # use 75% from popular and backfill with random from interview_videos and kvl_videos
        #

        popularity = get_popularity()

        for (video_id, pop) in sorted(
            popularity.items(), key=lambda item: item[1], reverse=True
        )[:togo]:
            if video_id in video_index:
                video = video_index[video_id]
                print(
                    f" * suggesting (based on popularity: {pop}), title: [{video['title']}]",
                )
                videos.append(video)

    togo = max(count - len(videos), 0)
    all_videos = interview_videos + kvl_videos + kview_videos

    if togo and len(all_videos) > togo:
        for video in random.sample(all_videos, togo):
            print(f" * suggesting (random), title: [{video['title']}]")
            videos.append(video)

    return videos


def _extend_info(video: Dict) -> Dict:

    parts = re.split(r"\s+-\s+", video["title"])
    if len(parts) == 1:
        if "with " in video["title"]:
            video_artist = " ".join(re.split(r"\s+with\s+", video["title"])[1:])
            video_title = video["title"]
        else:
            video_artist, video_title = (video["title"], video["title"])
    elif len(parts) == 2:
        video_artist, video_title = parts
    else:
        video_artist, video_title = (parts[0], parts[-1])

    if "upload_date" in video:
        m = re.search(r"(\d{2})\/\d{2}\/(\d{4})", video["upload_date"])
        extracted_month, extracted_year = (int(x) for x in m.groups())
    else:

        m = re.search(r".*\/uploads\/(\d{4})\/(\d{2})\/.*", video["image_url"])
        if m:
            extracted_year, extracted_month = (int(x) for x in m.groups())
        else:
            extracted_year, extracted_month = (
                datetime.date.today().year,
                datetime.date.today().month,
            )

    extracted_duration = None
    if "mp4_length" in video:
        extracted_duration = video["mp4_length"]

    extended_video = video.copy()
    extended_video.update(
        {
            "extracted_video_artist": video_artist,
            "extracted_video_title": video_title,
            "extracted_year": extracted_year,
            "extracted_month": datetime.date(
                extracted_year, extracted_month, 1
            ).strftime("%B"),
        }
    )

    extended_video.update({"extracted_duration": extracted_duration})

    return extended_video




