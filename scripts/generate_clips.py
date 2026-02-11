#!/usr/bin/env python

import glob
import json
import os
from typing import Dict

from dotenv import load_dotenv
from tqdm import tqdm

from lib.s3helper import S3Helper

load_dotenv()

TMP = os.getenv("TMP_DIR", f'{os.getcwd()}/storage/tmp')
bucket_name = os.getenv("S3_BUCKET_NAME", "arpedia-dev")


def _clipify(
        video_id: str, mp4: str, offset: float, duration: float, forcedownload: bool = False
) -> str | bool:
    dest_file = f"{TMP}/{video_id}_clip.mp4"
    if not forcedownload and os.path.exists(dest_file):
        return dest_file
    else:
        cmd = f"ffmpeg -y -nostats -loglevel 0 -ss {offset} -i {mp4} -t {duration} -c copy -movflags +faststart {dest_file}"
        print(" *", cmd)
        if os.system(cmd) == 0:
            return dest_file
        else:
            return False


def _get_video_length(video_id: str, mp4: str) -> float:
    local_file = f"{TMP}/{video_id}_clip.mp4"

    src = local_file if os.path.exists(local_file) else mp4

    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {src}"

    result = os.popen(cmd).read().strip()

    return float(result) if result else None


def generate_clip_and_write_to_s3(
        video: Dict, duration: float, forcedownload: bool = False, offset="auto"
):
    s3helper = S3Helper(bucket_name)
    video_id, mp4 = video["id"], video["mp4"]

    video_object = f"{video_id}.mp4"
    clip_object = f"{video_id}_clip_{int(duration)}s.mp4"

    video_exists = s3helper.file_exists(video_object)
    clip_exists = s3helper.file_exists(clip_object)
    
    local_file = f"{TMP}/{video_id}.mp4"
    local_exists = os.path.exists(local_file)

    if local_exists:
        mp4 = local_file

    if video_exists or local_exists:

        forcedownload = forcedownload or offset != "auto"

        if "mp4_length" not in video or not video["mp4_length"]:
            video_length = _get_video_length(video_id, mp4)
            if video_length:
                video["mp4_length"] = video_length
            else:
                print(" *", f"ERROR: could not get video length for {video_id}")
                return False

        # length = video["mp4_length"] if video["mp4_length"] else 0
        # if float(length) < 1:
        #     print(" *", f"ERROR: video length is less than 1 second for {video_id}")
        #     return False
        # process offset

        actual_offset = 0

        if offset == "auto":
            actual_offset = max(
                0, float(video["mp4_length"]) / 2.0 - float(duration) / 2.0
            )
        else:
            if 0 <= float(offset) <= (float(video["mp4_length"]) - float(duration)):
                actual_offset = offset

        if not forcedownload and clip_exists:
            video["mp4_clip"] = f"https://s3.amazonaws.com/{bucket_name}/{clip_object}"
        else:

            local_clip_file = _clipify(
                video_id, mp4, actual_offset, duration, forcedownload
            )

            if local_clip_file:
                s3helper.put_file(clip_object, local_clip_file)
                print(" *", f"uploaded {clip_object}")
                print(" *", f"removing {local_clip_file}")
                os.remove(local_clip_file)
                video[
                    "mp4_clip"
                ] = f"https://s3.amazonaws.com/{bucket_name}/{clip_object}"

        return video

    return False


def lookup_video_overrides(video):
    """potentially update the dict with any clip overrides (CLIP_OFFSET/CLIP_LENGTH)" \""""

    video_id = video["id"]
    OVERRIDES_CONFIG = "storage/config/clip_overrides.json"
    if os.path.exists(OVERRIDES_CONFIG):
        with open(OVERRIDES_CONFIG, encoding="utf-8") as f:
            overrides = json.loads(f.read())
            if video_id in overrides:
                video.update(overrides[video_id])

    return video


if __name__ == "__main__":

    CLIP_OFFSET = "clip_offset"
    CLIP_LENGTH = "clip_length"

    s3helper = S3Helper(bucket_name)

    manifest_folder = "storage/imported_videos"

    print(" *", f"globbing {manifest_folder}...")
    manifest_files = glob.glob(f"{manifest_folder}/*.json")

    print(" *", f"found {len(manifest_files)} videos...")

    for fname in tqdm(manifest_files):
        video = None

        with open(fname, encoding="utf-8") as f:
            video = json.loads(f.read())

        if not video:
            print(" *", f"ERROR {fname}")

        else:
            # look up in the config/offsets.json if there's an
            # override for this video

            video = lookup_video_overrides(video)

            OFFSET = video[CLIP_OFFSET] if CLIP_OFFSET in video else "auto"
            DURATION = video[CLIP_LENGTH] if CLIP_LENGTH in video else 20.0

            new_manifest = generate_clip_and_write_to_s3(
                video, duration=DURATION, offset=OFFSET
            )

            if new_manifest:
                with open(fname, "w") as f:
                    f.write(json.dumps(new_manifest, indent=2, ensure_ascii=False))
            else:
                # video must not exist so delete json
                print(" *", f"remove {fname}, [{video['title']}]")
                os.remove(fname)
