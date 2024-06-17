#!/usr/bin/env python

import yake
import json
import os
import glob
import argparse
import requests
import requests_cache
import hashlib
import time

from datetime import datetime
from s3helper import S3Helper
from dev_utils import image_url_to_data_uri
from typing import Dict, List
from external_videos import get_external_videos
from kview_videos import get_kview_videos
from yt_dlp import YoutubeDL
from dotenv import load_dotenv, dotenv_values
from s3helper import S3Helper
from typing import Dict
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

config = dotenv_values(".env")
TMP = os.getenv("TMP_DIR", f'{os.getcwd()}/tmp')
bucket_name = os.getenv("S3_BUCKET_NAME", "arpedia-dev")
source_ip = os.getenv("KAPI_SOURCE_IP", "http://174.138.94.71")
source_url = os.getenv("KAPI_SOURCE_URL", "https://kadist.mooresolutions.io")


requests_cache.CachedSession(
    cache_name="kvl_cache", backend="sqlite", expire_after=60 * 96
)  # minutes

s3helper = S3Helper(bucket_name)

# START DOWNLOAD FUNCTIONS
def cloudflare_url(url: str) -> str:
    # replace "http://54.218.253.163" with "https://kadist.org"
    url = url.replace('https://kadist.org', source_url)
    print(" *", f"replacing {source_ip} with {source_url}")
    return url.replace(source_ip, source_url)


def rm_json_files(folder: str):
    for filename in os.listdir(folder):
        if filename.endswith(".json"):
            os.remove(os.path.join(folder, filename))


def url_exists(url):
    r = requests.head(url)
    return r.status_code == 200


def generate_id(mp4: str) -> str:
    return hashlib.md5(mp4.encode("utf8")).hexdigest()


def generate_tags(text: str) -> List[str]:
    #
    # https://github.com/LIAAD/yake
    #

    stop_tags = ["film", "video", "art"]

    language = "en"
    max_ngram_size = 3
    deduplication_thresold = 0.9
    deduplication_algo = "seqm"
    windowSize = 1
    numOfKeywords = 20 if len(text.split()) > 36 else 10

    custom_kw_extractor = yake.KeywordExtractor(
        lan=language,
        n=max_ngram_size,
        dedupLim=deduplication_thresold,
        dedupFunc=deduplication_algo,
        windowsSize=windowSize,
        top=numOfKeywords,
        features=None,
    )
    keywords = custom_kw_extractor.extract_keywords(text)

    return [tag for (tag, confidence) in keywords if tag.lower() not in stop_tags]


def generate_abbreviated_description(description: str) -> str:
    return description.split(".")[0]


def download_video_file_to_mp4(url: str):
    dest_file = f"{TMP}/{generate_id(url)}.mp4"
    if os.path.exists(dest_file):
        return dest_file
    else:
        cmd = f"/usr/bin/ffmpeg -y -nostats -loglevel 0 -headers $'referer: https://kadist.org/' -i \"{url}\" -map 0:p:1? -c copy -bsf:a aac_adtstoasc {dest_file}"
        call = os.system(cmd)
        result = os.popen(cmd).read().strip()
        if result:
            print("result", result)
        if call == 0:
            return dest_file
        else:
            print("could not download file from", url, "to", dest_file)
            return False


def write_manifest(video_type: str, manifest: Dict, manifest_folder: str):

    assert "id" in manifest
    assert "title" in manifest
    assert "description" in manifest
    assert "abbreviated_description" in manifest
    assert "tags" in manifest
    assert "mp4" in manifest
    assert "image_url" in manifest

    # if not manifest['image_url']:
    manifest["image_data_uri"] = image_url_to_data_uri(manifest["image_url"])

    print(" *", f"write_manifest [type: {video_type}], ID: {manifest['id']}")

    manifest["type"] = video_type.lower()
    with open(f"{manifest_folder}/{manifest['id']}.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2, ensure_ascii=False))


def save_video_as_mp4(url: str, cleanup: bool = True):

    video_id = generate_id(url)
    video_duration = None
    video_object = f"{video_id}.mp4"

    if not s3helper.file_exists(video_object):
        print("No file exist in the bucket")
        local_tmp_file = download_video_file_to_mp4(url)
        if local_tmp_file:
            print(f"save_video_as_mp4::writing: {local_tmp_file} for {url} to bucket with name {video_object}")
            # conditionally save mp4
            s3helper.put_file(video_object, local_tmp_file, only_if_modified=True)
            # remove local tmp file
            cmd = f"/usr/bin/ffmpeg -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {local_tmp_file}"
            video_duration = os.popen(cmd).read().strip()
            if cleanup:
                print(f"save_video_as_mp4::cleaning up: {local_tmp_file}")
                # remove local tmp file
                os.remove(local_tmp_file)


            print(f"save_video_as_mp4::video_duration: {video_duration}")
        else:
            print(" *", f"skipping [{url}] not mp4")
        return video_id, video_duration
    else:
        local_tmp_file = download_video_file_to_mp4(url)
        if local_tmp_file:
            cmd = f"/usr/bin/ffmpeg -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {local_tmp_file}"
            video_duration = os.popen(cmd).read().strip()
            print(f"save_video_as_mp4::video_duration: Video exists remote")
            if cleanup:
                os.remove(local_tmp_file)
            return video_id, video_duration

        print("file already exists on bucket ", video_id)
        return video_id, False


def fetch_kvl(args, manifest_folder: str):
    print(" *", "fetching kvl...")
    payload = {
        "not_null": [
            "video_url",
            "image_url",
            "artist_name",
            "title",
            "description",
            "permalink",
            "image_dimensions",
        ],
        "filters": {"organization": ["kadist"], "object_type": ["collection"]},
    }

    url = "https://arpedia.herokuapp.com/arpedia/v1/not_null_search?count=1500"

    r = requests.post(url, json=payload)
    if r.status_code == requests.codes.ok:
        for x in tqdm(r.json()["results"]):
            url = x["external_key"]
            url = url.replace('https://kadist.org', source_ip)
            url = url.replace(source_url, source_ip)
            print(f"fetch_kvl::fetching: {url}")
            req = requests.get(url)
            work_details = {}
            if req.status_code == requests.codes.ok:
                work_details = req.json()
            # grab the video from kadist and put it on arpedia's bucket
            video_id, video_duration = save_video_as_mp4(x["video_url"], False)
            if video_id:
                if type(x["region"]) == list:
                    x["region"] = x["region"][0]
                video = {
                    "id": video_id,
                    "title": "{} - {}".format(x["artist_name"], x["title"]),
                    "image_url": x["image_url"],
                    "description": x["description"],
                    "permalink": cloudflare_url(x["permalink"]),
                    "image_width": x["image_dimensions"][0],
                    "image_height": x["image_dimensions"][1],
                    "region": x["region"],
                    "mp4": f"https://s3.amazonaws.com/{bucket_name}/{video_id}.mp4",
                    "abbreviated_description": generate_abbreviated_description(
                        x["description"]
                    ),
                    "tags": generate_tags(x["description"]),
                    "work_details": work_details,
                    "mp4_length": video_duration,
                }
                write_manifest("kvl", video, manifest_folder)
                clip_duration = 20.0
                print("creating new clip for", video_id)
                clip_manifest = generate_clip_and_write_to_s3(video, clip_duration)
                if clip_manifest:
                    write_manifest("kvl", clip_manifest, manifest_folder)
                else:
                    print("Failed to generate clip")

                vfile = f"{TMP}/{video_id}.mp4"
                if os.path.exists(vfile):
                    os.remove(vfile)
            else:
                print("No video id for url", url, video_id, video_duration)


def fetch_kadist(args, manifest_folder: str):
    print(" *", "fetching kadist...")

    class VimeoDownloader:
        def __init__(self, manifest_folder, video):
            self.manifest = video
            self.manifest_folder = manifest_folder
            self.video_type = "interview"

        # START VIDEO REMOVAL
        def save_video_create_manifest(self, dest_file):
            s3helper.put_file(f"{self.manifest['id']}.mp4", dest_file)
            time.wait(5)
            clipManifest = self.generate_save_clip()
            if os.path.exists(dest_file):
                print(f" *", f"removing {dest_file}")
                os.remove(dest_file)
            write_manifest(self.video_type, self.manifest, self.manifest_folder)
            if clipManifest:
                write_manifest("clip", self.manifest, self.manifest_folder)
            else:
                print(" *", "No clip manifest found", dest_file)

        def generate_save_clip(self):
            duration = self.manifest.duration if self.manifest.duration else None
            return generate_clip_and_write_to_s3(self.manifest, duration)
        def callback(self, d):
            if d["status"] == "finished":
                self.save_video_create_manifest(d["filename"])

        def process_description(self, s):
            return s.split("\n")[0].strip()

        def format_upload_date(self, s):
            return datetime.strptime(s, "%Y%m%d").strftime("%m/%d/%Y")

        def download_video(self, url: str):

            ydl_opts = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": f"{TMP}/{generate_id(url)}.mp4",
                "noplaylist": True,
                "quiet": args.verbose,
                "progress_hooks": [self.callback],
            }

            with YoutubeDL(ydl_opts) as ydl:
                try:
                    video_id = generate_id(url)

                    self.manifest["id"] = video_id
                    self.manifest[
                        "mp4"
                    ] = f"https://s3.amazonaws.com/{bucket_name}/{video_id}.mp4"

                    if self.manifest["tags"]:
                        self.manifest["tags"] = ["vimeo"] + self.manifest["tags"]

                    dest_file = f"{TMP}/{video_id}.mp4"

                    if s3helper.file_exists(dest_file):
                        write_manifest(
                            self.video_type, self.manifest, self.manifest_folder
                        )
                    else:
                        if os.path.exists(dest_file):
                            self.save_video_create_manifest(dest_file)
                        else:
                            ydl.download([url])

                except Exception as e:
                    print("Error Downloading")
                    print(str(e))

    with open("config_files/kadist_videos.json") as f:
        videos = json.loads(f.read())

        for x in tqdm(videos):

            video = {
                "title": x["title"],
                "image_url": x["image_url"],
                "description": x["description"],
                "permalink": cloudflare_url(x["permalink"]),
                "image_width": x["image_width"],
                "image_height": x["image_height"],
                "region": x["region"],
                "abbreviated_description": generate_abbreviated_description(
                    x["description"]
                ),
                "tags": generate_tags(x["description"]),
            }

            VimeoDownloader(manifest_folder, video).download_video(x["raw_video_url"])


def fetch_external(args, manifest_folder):
    print(" *", "fetch_external videos")

    class YoutubeDownloader:
        def __init__(self, manifest_folder):
            self.manifest_folder = manifest_folder
            self.video_type = "external"

        def save_video_create_manifest(self, dest_file):
            s3helper.put_file(f"{self.manifest['id']}.mp4", dest_file)
            generate_clip_and_write_to_s3()
            if os.path.exists(dest_file):
                print(f" *", f"removing {dest_file}")
                os.remove(dest_file)
            write_manifest(self.video_type, self.manifest, self.manifest_folder)

        def callback(self, d):
            if d["status"] == "finished":
                self.save_video_create_manifest(d["filename"])

        def process_description(self, s):
            return s.split("\n")[0].strip()

        def format_upload_date(self, s):
            return datetime.strptime(s, "%Y%m%d").strftime("%m/%d/%Y")

        def download_video(self, url: str):

            ydl_opts = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": f"{TMP}/{generate_id(url)}.mp4",
                "noplaylist": True,
                "quiet": args.verbose,
                "progress_hooks": [self.callback],
            }

            with YoutubeDL(ydl_opts) as ydl:
                try:
                    info_dict = ydl.extract_info(url, download=False)
                    "".join(filter(str.isalpha, info_dict.get("id")))
                    video_title = info_dict.get("title", None)
                    view_count = info_dict.get("view_count", 0)
                    description = info_dict.get("description", None)
                    upload_date = info_dict.get("upload_date", None)
                    tags = info_dict.get("tags", [])
                    image_url = info_dict.get("thumbnail", None)

                    if description.startswith("Enjoy the videos"):
                        description = ""

                    self.manifest = {
                        "title": video_title,
                        "description": self.process_description(description),
                        "abbreviated_description": generate_abbreviated_description(
                            description
                        ),
                        "view_count": view_count,
                        "upload_date": self.format_upload_date(upload_date),
                        "image_url": image_url,
                        "tags": tags,
                        "region": "All",
                    }

                    video_id = generate_id(url)
                    self.manifest["id"] = video_id
                    self.manifest[
                        "mp4"
                    ] = f"https://s3.amazonaws.com/{bucket_name}/{video_id}.mp4"

                    if self.manifest["tags"]:
                        self.manifest["tags"] = ["youtube"] + self.manifest["tags"]

                    self.manifest["tags"] += generate_tags(self.manifest["description"])

                    self.manifest["permalink"] = cloudflare_url(url)

                    dest_file = f"{TMP}/{video_id}.mp4"

                    if s3helper.file_exists(dest_file):
                        write_manifest(
                            self.video_type, self.manifest, self.manifest_folder
                        )
                    else:
                        if os.path.exists(dest_file):
                            self.save_video_create_manifest(dest_file)
                        else:
                            ydl.download([url])

                except Exception as e:
                    print(str(e))

    if args.rm:
        s3helper.rm_files(args.rm)
    else:
        external_videos = get_external_videos()
        print(" *", f"fetch_external, processing {len(external_videos)} videos")

        for url in tqdm(external_videos):
            YoutubeDownloader(manifest_folder).download_video(url)


def fetch_kviews(args, manifest_folder):
    kview_videos = get_kview_videos()
    print(" *", f"fetch_kview_videos, processing {len(kview_videos)} videos")

    video_type = "kview"

    for kview in tqdm(kview_videos):

        video_id, video_duration = save_video_as_mp4(kview["video_url"], False)

        if video_id:
            manifest = {
                "id": video_id,
                "mp4": f"https://s3.amazonaws.com/{bucket_name}/{video_id}.mp4",
                "title": kview["title"],
                "description": kview["description"],
                "permalink": cloudflare_url(kview["permalink"]),
                "abbreviated_description": generate_abbreviated_description(
                    kview["description"]
                ),
                "upload_date": datetime.today().strftime("%m/%d/%Y"),  # todo
                "image_url": kview["image_url"],
                "tags": generate_tags(kview["description"]),
                "region": "All",
                "mp4_length": video_duration,
            }


            write_manifest(video_type, manifest, manifest_folder)
            clip_duration = 20.0
            print("creating new clip for", video_id, manifest["mp4"], manifest["mp4_length"])
            clip_manifest = generate_clip_and_write_to_s3(manifest, clip_duration)
            if clip_manifest:
                write_manifest("kvl", clip_manifest, manifest_folder)
            else:
                print("Failed to generate clip")
            vfile = f"{TMP}/{video_id}.mp4"
            if os.path.exists(vfile):
                os.remove(vfile)

        else:
            print(" *", f"fetch_kviews, skipping {kview['video_url']} - NOT FOUND")

# END DOWNLOAD FUNCTIONS

# START GENERATE CLIPS FUNCTIONS
def _clipify(
        video_id: str, mp4: str, offset: float, duration: float, forcedownload: bool = False
) -> str:
    dest_file = f"{TMP}/{video_id}_clip.mp4"
    if not forcedownload and os.path.exists(dest_file):
        return dest_file
    else:
        cmd = f"/usr/bin/ffmpeg -y -nostats -loglevel 0 -ss {offset} -i {mp4} -t {duration} -c copy {dest_file}"
        print(" *", cmd)
        if os.system(cmd) == 0:
            return dest_file
        else:
            return False


def _get_video_length(video_id: str, mp4: str) -> float:
    local_file = f"{TMP}/{video_id}_clip.mp4"

    src = local_file if os.path.exists(local_file) else mp4

    cmd = f"/usr/bin/ffmpeg -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {src}"

    result = os.popen(cmd).read().strip()

    return float(result) if result else None


def generate_clip_and_write_to_s3(
        video: Dict, duration: float, forcedownload: bool = False, offset="auto"
):
    video_id, mp4 = video["id"], video["mp4"]

    video_object = f"{video_id}.mp4"
    clip_object = f"{video_id}_clip_{int(duration)}s.mp4"

    video_exists = s3helper.file_exists(video_object)
    clip_exists = s3helper.file_exists(clip_object)

    if video_exists:

        forcedownload = forcedownload or offset != "auto"

        if "mp4_length" not in video:
            video_length = _get_video_length(video_id, mp4)
            if video_length:
                video["mp4_length"] = video.get("mp4_length", video_length)
            else:
                print(" *", f"ERROR: could not get video length for {video_id}")
                return False

        length = video["mp4_length"] if video["mp4_length"] else 0
        if float(length) < 1:
            print(" *", f"ERROR: video length is less than 1 second for {video_id}")
            return False
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
    OVERRIDES_CONFIG = "config_files/clip_overrides.json"
    if os.path.exists(OVERRIDES_CONFIG):
        with open(OVERRIDES_CONFIG, encoding="utf-8") as f:
            overrides = json.loads(f.read())
            if video_id in overrides:
                video.update(overrides[video_id])

    return video


# START CLIPS MAIN
def genClipsMain():
    CLIP_OFFSET = "clip_offset"
    CLIP_LENGTH = "clip_length"

    s3helper = S3Helper(bucket_name)

    manifest_folder = "imported_videos"

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
            # look up in the config_files/offsets.json if there's an
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


# START MAIN
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="video downloader")

    parser.add_argument(
        "--rm", action="store", nargs="+", help="remove files from bucket"
    )

    parser.add_argument(
        "-v", "--verbose", help="increase output verbosity", action="store_true"
    )

    args = parser.parse_args()

    manifest_folder = "imported_videos"

    rm_json_files(manifest_folder)

    fetch_kvl(args, manifest_folder)# should generate clip
    fetch_kadist(args, manifest_folder)# should generate clip
    fetch_external(args, manifest_folder)# should generate clip
    fetch_kviews(args, manifest_folder)# should generate clip
