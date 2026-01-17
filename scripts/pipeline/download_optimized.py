#!/usr/bin/env python

import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime
from typing import Dict
from typing import List

import requests
import requests_cache
import yake
from dotenv import dotenv_values
from dotenv import load_dotenv
from tqdm import tqdm
from yt_dlp import YoutubeDL


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from lib.app_utils import clear_temporary_videos
from lib.dev_utils import image_url_to_data_uri
from lib.s3helper import S3Helper
from scripts.pipeline.external_videos import get_external_video_data
from scripts.pipeline.kview_videos import get_kview_videos

# Ensure the project root is in the python path

load_dotenv()

config = dotenv_values(os.path.join(project_root, ".env"))
TMP = os.getenv("TMP_DIR", f'{os.getcwd()}/storage/tmp')
bucket_name = os.getenv("S3_BUCKET_NAME", "ktv")
source_ip = os.getenv("KAPI_SOURCE_IP")
source_url = os.getenv("KAPI_SOURCE_URL")


requests_cache.CachedSession(
    cache_name="storage/caches/kvl_cache", backend="sqlite", expire_after=60 * 96
)  # minutes

s3helper = S3Helper(bucket_name)

# START DOWNLOAD FUNCTIONS
## Deprecated
def cloudflare_url(url: str) -> str:
    return url


def rm_json_files(folder: str):
    for filename in os.listdir(folder):
        if filename.endswith(".json"):
            os.remove(os.path.join(folder, filename))


def url_exists(url):
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False



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
    if not description:
        return ""
    return description.split(".")[0]

def download_video_file_to_mp4(url: str):
    dest_file = f"{TMP}/{generate_id(url)}.mp4"
    if os.path.exists(dest_file):
        print("local file exits serving it back!")
        return dest_file
    else:
        print(f"no local file attempting to download: {url}")
        # Optimization: Use ffmpeg with specific HLS options and a clear error level.
        # -headers: Required for S3/HLS access if Referer is checked.
        # -i: Input URL (works for both MP4 and M3U8).
        # -c copy: Re-mux instead of re-encode to save CPU and time.
        # -bsf:a aac_adtstoasc: Required when muxing HLS AAC into MP4.
        # -map 0:p:1?: Safely attempts to map the second program/stream if available.

        referer = "https://kadist.org/"
        cmd = (
            f'ffmpeg -y -hide_banner -loglevel error '
            f'-headers "Referer: {referer}" '
            f'-i "{url}" '
            f'-c copy -bsf:a aac_adtstoasc '
            f'-movflags +faststart '
            f'"{dest_file}"'
        )

        try:
            call = os.system(cmd)
            if call == 0 and os.path.exists(dest_file) and os.path.getsize(dest_file) > 0:
                return dest_file
            else:
                if os.path.exists(dest_file):
                    os.remove(dest_file)
                print("could not download or mux file", cmd)
                return False
        except Exception as e:
            print(f"ffmpeg execution failed: {e}")
            if os.path.exists(dest_file):
                os.remove(dest_file)
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
    image_url = manifest.get("image_url")
    if not image_url or not url_exists(image_url):
        print(f"Invalid or missing image URL: {image_url}")
        manifest["image_data_uri"] = None  # Or assign a default placeholder
    else:
        manifest["image_data_uri"] = image_url_to_data_uri(image_url)

    print(" *", f"write_manifest [type: {video_type}], ID: {manifest['id']}")

    manifest["type"] = video_type.lower()
    with open(f"{manifest_folder}/{manifest['id']}.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2, ensure_ascii=False))


def save_video_as_mp4(url: str, cleanup: bool = True):
    """
    Save a video from a given URL as an MP4 file to a cloud storage bucket. This
    function verifies if the file already exists in the cloud storage before
    proceeding with the download, and optionally cleans up temporary files used
    during the process. It also retrieves the duration of the video using the
    ffprobe utility. If the video is not in MP4 format or cannot be retrieved,
    the function skips the processing.

    Parameters:
        url (str): The URL of the video to download and save.
        cleanup (bool, optional): Indicates whether to delete the locally downloaded
            temporary file after processing. Defaults to True.

    Returns:
        Tuple[str, Union[str, bool]]: The unique identifier of the saved video file
            and the duration of the video as a string if successful. Returns False
            as the second element of the tuple if downloading or processing the
            video fails.
    """
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
            cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {local_tmp_file}"
            video_duration = os.popen(cmd).read().strip()
            print("video duration", video_duration)
            if cleanup:
                print(f"save_video_as_mp4::cleaning up: {local_tmp_file}")
                # remove local tmp file
                os.remove(local_tmp_file)
            print(f"save_video_as_mp4::video_duration: {video_duration}")
        else:
            print(" *", f"skipping [{url}] not mp4")
        return video_id, video_duration
    else:
        print("file already exists on bucket ", video_id)
        local_tmp_file = download_video_file_to_mp4(url)
        if local_tmp_file:
            cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {local_tmp_file}"
            video_duration = os.popen(cmd).read().strip()
            print(f"save_video_as_mp4::video_duration: Video exists remote")
            if cleanup:
                os.remove(local_tmp_file)
            return video_id, video_duration

        print("unable to download", video_id)
        return video_id, False


def fetch_kvl(args, manifest_folder: str):
    """
    Fetches and processes videos and associated metadata from a remote service, saves them
    locally as MP4 files, generates additional video clips, and writes the results to a
    specified manifest folder. The function also fetches additional details for each video
    from related endpoints and includes these in the manifest.

    Attributes
    ----------
    args : Any
        The argument list or dictionary passed to the function. Nature of `args` is assumed
        to be understood in the broader context of the application.
    manifest_folder : str
        The directory where the generated manifest files will be saved.

    Parameters
    ----------
    args : Any
        Parameters or arguments required for the data-fetching operation.
    manifest_folder : str
        The path or location of the folder where manifest files are to be stored.

    Returns
    -------
    None
        This function does not return any value. Instead, it performs operations involving
        network requests, file writing, and data processing.

    Raises
    ------
    requests.exceptions.RequestException
        If there is an issue with the HTTP request operations.
    ValueError
        If the expected data is missing or malformed during processing.
    TypeError
        If the data structure for attributes like `region` is not as expected.
    OSError
        If file operations, such as removing temporary video files, encounter an error.
    """
    print(" *", "starting fetch_kvl")
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
            if not url_exists(url):
                print(" *", f"skipping {url}")
                continue
            url = cloudflare_url(url)
            print(f"fetch_kvl::fetching: {url}")
            req = requests.get(url)
            work_details = {}
            if req.status_code == requests.codes.ok:
                work_details = req.json()
            # grab the video from kadist and put it on arpedia's bucket
            video_id, video_duration = save_video_as_mp4(x["video_url"], False)
            if video_id:
                if "region" in x and type(x["region"]) == list:
                    x["region"] = x["region"][0] # one off issue

                if not "region" in x:
                    x["region"] = "unknown"

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
                
                clip_duration = 20.0
                print("creating new clip for", video_id)
                clip_manifest = generate_clip_and_write_to_s3(video, clip_duration)
                if clip_manifest:
                    video.update(clip_manifest)
                else:
                    print("Failed to generate clip")

                write_manifest("kvl", video, manifest_folder)

                vfile = f"{TMP}/{video_id}.mp4"
                if os.path.exists(vfile):
                    os.remove(vfile)
            else:
                print("No video id for url", url, video_id, video_duration)
        print(" *", "fetch_kvl::completed")


def fetch_kadist(args, manifest_folder: str):
    """
    def fetch_kadist(args, manifest_folder: str):
        """
    print(" *", "fetching starting fetch_kadist")

    class VimeoDownloader:
        def __init__(self, manifest_folder, video):
            self.manifest = video
            self.manifest_folder = manifest_folder
            self.video_type = "interview"

        # START VIDEO REMOVAL
        def save_video_create_manifest(self, dest_file):
            s3helper.put_file(f"{self.manifest['id']}.mp4", dest_file)
            
            # Use a copy of manifest to avoid in-place modification issues if any
            temp_video = self.manifest.copy()
            updated_video = self.generate_save_clip(temp_video)
            if updated_video:
                self.manifest.update(updated_video)
            else:
                print(" *", "No clip manifest found or generation failed", dest_file)

            if os.path.exists(dest_file):
                print(f" *", f"removing {dest_file}")
                os.remove(dest_file)

            write_manifest(self.video_type, self.manifest, self.manifest_folder)

        def generate_save_clip(self, video_dict=None):
            if video_dict is None:
                video_dict = self.manifest
            print("generating clip...")
            return generate_clip_and_write_to_s3(video_dict, 20.0)
        def callback(self, d):
            if d["status"] == "finished":
                self.save_video_create_manifest(d["filename"])

        def process_description(self, s):
            if not s:
                return ""
            return s.split("\n")[0].strip()

        def format_upload_date(self, s):
            return datetime.strptime(s, "%Y%m%d").strftime("%m/%d/%Y")

        def download_video(self, url: str):

            ydl_opts = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": f"{TMP}/{generate_id(url)}.mp4",
                "noplaylist": True,
                "verbose": True,
                "progress_hooks": [self.callback],
                "cookies": f'{os.getcwd()}/cookies.txt',
                "http_headers": {
                    "User-Agent": "AppleCoreMedia/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
                }
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

                    # Check S3 by key, not local path
                    if s3helper.file_exists(f"{video_id}.mp4"):
                        duration = 20.0
                        temp_video = self.manifest.copy()
                        updated_video = generate_clip_and_write_to_s3(temp_video, duration)
                        if updated_video:
                            self.manifest.update(updated_video)
                        
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

    with open(os.path.join("storage", "config", "kadist_videos.json")) as f:
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

    print(' *', 'fetch_kadist completed')


def fetch_external(args, manifest_folder):
    print(" *", "starting fetch_external")

    class YoutubeDownloader:
        def __init__(self, manifest_folder):
            self.manifest_folder = manifest_folder
            self.video_type = "external"

        def save_video_create_manifest(self, dest_file):
            # Ensure we have a valid video dictionary
            if not hasattr(self, 'manifest') or not self.manifest:
                print("Error: self.manifest is not initialized")
                return

            s3helper.put_file(f"{self.manifest['id']}.mp4", dest_file)
            duration = 20.0
            
            # Use a copy of manifest to avoid in-place modification issues if any
            temp_video = self.manifest.copy()
            updated_video = generate_clip_and_write_to_s3(temp_video, duration)
            if updated_video:
                self.manifest.update(updated_video)
            else:
                print("No clip manifest found or generation failed")
            
            write_manifest(self.video_type, self.manifest, self.manifest_folder)
            
            if os.path.exists(dest_file):
                os.remove(dest_file)

        def callback(self, d):
            if d["status"] == "finished":
                self.save_video_create_manifest(d["filename"])

        def process_description(self, s):
            if not s:
                return ""
            return s.split("\n")[0].strip()

        def format_upload_date(self, s):
            if not s:
                return datetime.today().strftime("%m/%d/%Y")
            try:
                return datetime.strptime(s, "%Y%m%d").strftime("%m/%d/%Y")
            except (ValueError, TypeError):
                return datetime.today().strftime("%m/%d/%Y")

        def download_video(self, url: str, extraInfo: dict = {}):

            ydl_opts = {
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": f"{TMP}/{generate_id(url)}.mp4",
                "noplaylist": True,
                "verbose": True,
                "progress_hooks": [self.callback],
                "http_headers": {
                    "User-Agent": "AppleCoreMedia/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
                }
            }
            # User Agent Missing?
            with YoutubeDL(ydl_opts) as ydl:
                try:
                    info_dict = ydl.extract_info(url, download=False)
                    video_title = extraInfo.get("title", info_dict.get("title", ""))
                    view_count = info_dict.get("view_count", 0)
                    description = extraInfo.get("description", '')
                    upload_date = info_dict.get("upload_date", None)
                    tags = generate_tags(description) if description else []
                    image_url = extraInfo.get("image_url", '')
                    collection = extraInfo.get("collection", None)
                    images = extraInfo.get("images", [])
                    permalink = extraInfo.get("permalink", None)

                    if isinstance(image_url, dict):
                        image_url = image_url.get("url", None)
                    if collection:
                        tags.append(collection)


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
                        "images": images,
                        "collection": collection,
                        "permalink": permalink
                    }

                    video_id = generate_id(url)
                    self.manifest["id"] = video_id
                    self.manifest[
                        "mp4"
                    ] = f"https://s3.amazonaws.com/{bucket_name}/{video_id}.mp4"

                    if self.manifest["tags"]:
                        self.manifest["tags"] = ["youtube"] + self.manifest["tags"]

                    self.manifest["tags"] += generate_tags(self.manifest["description"])

                    self.manifest["permalink"] = permalink

                    dest_file = f"{TMP}/{video_id}.mp4"

                    # Check S3 by key, not local path
                    if s3helper.file_exists(f"{video_id}.mp4"):
                        duration = 20.0
                        temp_manifest = generate_clip_and_write_to_s3(self.manifest, duration)
                        if temp_manifest:
                            self.manifest.update(temp_manifest)
                        
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
        external_videos = get_external_video_data()
        print(" *", f"fetch_external, processing {len(external_videos)} videos")

        try:
            for data in tqdm(external_videos):
                YoutubeDownloader(manifest_folder).download_video(data["video_url"], data)
        except KeyboardInterrupt:
            print("\n * Interrupted by user. Cleaning up and exiting fetch_external...")
            
    print(" *", "fetch_external completed")

def fetch_kviews(args, manifest_folder):
    print(" *", "starting fetch_kviews")
    kview_videos = get_kview_videos()

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
            clip_duration = 20.0
            print("creating new clip for", video_id, manifest["mp4"], manifest["mp4_length"])
            clip_manifest = generate_clip_and_write_to_s3(manifest, clip_duration)
            if clip_manifest:
                manifest.update(clip_manifest)
            else:
                print("Failed to generate clip")

            write_manifest(video_type, manifest, manifest_folder)

            vfile = f"{TMP}/{video_id}.mp4"
            if os.path.exists(vfile):
                os.remove(vfile)

        else:
            print(" *", f"fetch_kviews, skipping {kview['video_url']} - NOT FOUND")
    print(" *", "fetch_kviews completed")

# END DOWNLOAD FUNCTIONS

# START GENERATE CLIPS FUNCTIONS
def _clipify(
        video_id: str, mp4: str, offset: float, duration: float, forcedownload: bool = False
) -> str | bool:
    dest_file = f"{TMP}/{video_id}_clip.mp4"
    if not forcedownload and os.path.exists(dest_file):
        return dest_file
    else:
        cmd = f"ffmpeg -y -nostats -loglevel error -ss {offset} -i {mp4} -t {duration} -c copy {dest_file}"
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
    video_id = video["id"]

    video_object = f"{video_id}.mp4"
    clip_object = f"{video_id}_clip_{int(duration)}s.mp4"

    print('generating clip from', video_object, 'and naming it', clip_object)
    video_exists = s3helper.file_exists(video_object)
    clip_exists = s3helper.file_exists(clip_object)
    local_file = f"{TMP}/{video_id}.mp4"
    local_exists = os.path.exists(local_file)

    mp4 = local_file if local_exists else video["mp4"]

    if video_exists or local_exists:
        print('video clip exists', video_id)
        forcedownload = forcedownload or offset != "auto"

        if "mp4_length" not in video or not video["mp4_length"]:
            print('no mp4_length')
            video_length = _get_video_length(video_id, mp4)
            if video_length:
                print('video length', video_length)
                video["mp4_length"] = video_length
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
            print("making clip")
            local_clip_file = _clipify(video_id, mp4, actual_offset, duration, forcedownload)

            if local_clip_file:
                s3helper.put_file(clip_object, local_clip_file)
                print(" *", f"uploaded {clip_object}")
                print(" *", f"removing {local_clip_file}")
                os.remove(local_clip_file)
                video[
                    "mp4_clip"
                ] = f"https://s3.amazonaws.com/{bucket_name}/{clip_object}"
            else:
                # If clip generation failed, we still want to keep existing mp4_clip if it exists
                if clip_exists:
                     video["mp4_clip"] = f"https://s3.amazonaws.com/{bucket_name}/{clip_object}"

        return video
    print("clip gen failed with no video exists?")
    return False


def lookup_video_overrides(video):
    video_id = video["id"]
    OVERRIDES_CONFIG = "storage/config/clip_overrides.json"
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


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="video downloader")

    # Fix: Use `store_true` for a flag-like behavior
    parser.add_argument(
        "--rm", action="store_true", help="remove files from bucket"
    )

    parser.add_argument(
        "-v", "--verbose", help="increase output verbosity", action="store_true"
    )

    args = parser.parse_args()

    manifest_folder = "storage/imported_videos"

    # Use args.rm instead of `remove`
    if args.rm:
        rm_json_files(manifest_folder)

    fetch_kviews(args, manifest_folder)  # should generate clip

    fetch_kadist(args, manifest_folder)  # should generate clip

    fetch_external(args, manifest_folder)  # should generate clip

    fetch_kvl(args, manifest_folder)  # should generate clip

    clear_temporary_videos(TMP)
