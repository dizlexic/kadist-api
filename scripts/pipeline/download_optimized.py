#!/usr/bin/env python

import argparse
import glob
import hashlib
import json
import os
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

from lib.app_utils import clear_temporary_videos
from lib.dev_utils import image_url_to_data_uri
from lib.s3helper import S3Helper
from scripts.pipeline.external_videos import get_external_videos
from scripts.pipeline.kview_videos import get_kview_videos

load_dotenv()

config = dotenv_values("../../.env")
TMP = os.getenv("TMP_DIR", f'{os.getcwd()}/storage/tmp')
bucket_name = os.getenv("S3_BUCKET_NAME", "arpedia-dev")
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
    """
    Remove all JSON files from a specified folder.

    This function iterates over all the files in the given folder and deletes
    any file that has a '.json' extension. It is designed to work with folders
    that contain files which need filtering and removal based on their extensions.

    Parameters:
    folder (str): The path to the folder in which JSON files will be removed.

    Raises:
    FileNotFoundError: If the specified folder does not exist.
    PermissionError: If the program does not have necessary permissions to access
    or delete files in the specified folder.
    """
    for filename in os.listdir(folder):
        if filename.endswith(".json"):
            os.remove(os.path.join(folder, filename))


def url_exists(url):
    """
    Checks the existence of a URL by making a HEAD request and verifying the HTTP status code.

    Parameters
    ----------
    url : str
        The URL to check for availability.

    Returns
    -------
    bool
        True if the URL exists and returns a status code of 200, otherwise False.

    Raises
    ------
    requests.exceptions.RequestException
        If there is an issue making the HTTP request.
    """
    r = requests.head(url)
    return r.status_code == 200


def generate_id(mp4: str) -> str:
    """
    Generate a unique identifier for the given input string.

    This function takes a string input, encodes it as UTF-8, and computes its MD5
    hash. The resulting hash is returned as a hexadecimal string. It is commonly
    used to generate consistent and unique identifiers for string data.

    Args:
        mp4 (str): The input string to hash.

    Returns:
        str: The MD5 hash of the input string represented as a hexadecimal value.
    """
    return hashlib.md5(mp4.encode("utf8")).hexdigest()


def generate_tags(text: str) -> List[str]:
    """
    Generate tags from a given text using the YAKE keyword extraction
    algorithm. The method filters out common stop tags and returns
    the most relevant keywords.

    Parameters:
        text (str): The input text from which the tags are extracted.

    Returns:
        List[str]: A list of the extracted tags as strings.

    Raises:
        None

    """
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
    """
    Generates an abbreviated description by extracting the first sentence
    from the provided text.

    Parameters:
        description: str
            A full textual description from which the first sentence
            will be extracted.

    Returns:
        str: The first sentence of the input description.

    """
    return description.split(".")[0]


def download_video_file_to_mp4(url: str):
    """
        Downloads a video file from a specified URL and saves it in MP4 format. The function checks
        if the file already exists locally; if so, it directly returns the local file path. Otherwise,
        it attempts to download the video using ffmpeg and save it to a temporary directory.

        Parameters:
        ----------
        url : str
            The URL of the video to be downloaded.

        Returns:
        -------
        str|bool
            The path to the downloaded MP4 file if successful, or False if the download fails.

        Raises:
        ------
        OSError
            If there is an issue executing the ffmpeg command during download.
    """
    dest_file = f"{TMP}/{generate_id(url)}.mp4"
    if os.path.exists(dest_file):
        print("local file exits serving it back!")
        return dest_file
    else:
        print("no local file attempting to download")
        cmd = f"ffmpeg -y -nostats -loglevel error -headers 'Referer: https://kadist.org/' -i \"{url}\" -map 0:p:1? -c copy -bsf:a aac_adtstoasc {dest_file}"
        call = os.system(cmd)
        if call == 0:
            return dest_file
        else:
            print("could not download file", cmd)
            return False


def write_manifest(video_type: str, manifest: Dict, manifest_folder: str):
    """
    Writes a manifest file for a given video type and metadata.

    The function validates that the required keys exist in the manifest dictionary, processes the
    image URL into a data URI if it is provided, and finally writes the manifest dictionary to a
    JSON file in the specified folder. The manifest type is converted to lowercase before saving.

    Args:
        video_type (str): The type of the video to associate with the manifest.
        manifest (Dict): A dictionary containing metadata about the video, such as 'id', 'title',
            'description', 'abbreviated_description', 'tags', 'mp4', and 'image_url'.
        manifest_folder (str): The folder path where the manifest file will be saved.

    Raises:
        AssertionError: If any of the required keys like 'id', 'title', 'description',
            'abbreviated_description', 'tags', 'mp4', or 'image_url' are missing
            in the manifest dictionary.
    """
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
    """
    def fetch_kadist(args, manifest_folder: str):
        """
    print(" *", "fetching kadist...")

    class VimeoDownloader:
        def __init__(self, manifest_folder, video):
            self.manifest = video
            self.manifest_folder = manifest_folder
            self.video_type = "interview"

        # START VIDEO REMOVAL
        def save_video_create_manifest(self, dest_file):
            s3helper.put_file(f"{self.manifest['id']}.mp4", dest_file)
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
            print("yt dl ")
            return generate_clip_and_write_to_s3(self.manifest, 20.0)
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
                "verbose": True,
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

    with open("config/kadist_videos.json") as f:
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
    """
    fetch_external(args, manifest_folder):
        Fetches external videos and processes them. It can either remove specified files
        from S3 if rm argument is provided or downloads and processes external videos.

        Parameters:
            args: Arguments passed to determine operation. Should include information
                  about the files to remove or the operation mode.
            manifest_folder: The folder path where the manifests will be stored.

    YoutubeDownloader:
        A class for handling the downloading and processing of YouTube videos.

        Attributes:
            manifest_folder: The folder path where the video manifests will be stored.
            video_type: The type of the video, defaults to "external".

        Methods:
            save_video_create_manifest(dest_file):
                Uploads the video file to S3, generates a clip and its manifest, and
                removes the local video file once done.

            callback(d):
                A callback function triggered periodically during the video download
                process. If the video download completes, this method saves the video
                and creates its manifest.

            process_description(s):
                Processes the input string to extract and clean up its first line.

            format_upload_date(s):
                Converts the input upload date string from "YYYYMMDD" format to
                "MM/DD/YYYY" format.

            download_video(url: str):
                Downloads the YouTube video specified by the given URL. Extracts
                metadata, processes the video, updates the manifest, and uploads the
                video and its details to S3. If the video is already available locally,
                it skips the download and uploads the pre-existing file.
    """
    print(" *", "fetch_external videos")

    class YoutubeDownloader:
        def __init__(self, manifest_folder):
            self.manifest_folder = manifest_folder
            self.video_type = "external"

        def save_video_create_manifest(self, dest_file):
            s3helper.put_file(f"{self.manifest['id']}.mp4", dest_file)
            duration = 20.0
            generate_clip_and_write_to_s3(self.manifest, duration)
            if os.path.exists(dest_file):
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
                "verbose": True,
                "progress_hooks": [self.callback],
            }

            with YoutubeDL(ydl_opts) as ydl:
                try:
                    info_dict = ydl.extract_info(url, download=False)
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
    """
    Fetch and process "KView" videos, save them as MP4 files, create their associated
    metadata, and store both videos and metadata into the appropriate locations. This
    function also generates short video clips for each full-length video and saves
    related metadata.

    Arguments:
        args: Command-line arguments or configuration parameter object required
              for the function's operations. Specific type and structure are not
              detailed here.
        manifest_folder (str): Directory path where video and clip metadata files
              (manifests) will be stored.

    Raises:
        None explicitly, but errors may occur due to network issues, file access
        permissions, or failures in helper functions invoked internally.

    Returns:
        None
    """
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
    """
    Create a video clip from an existing video file using FFmpeg.

    This function generates a video clip from the provided video file, starting from the specified
    offset and lasting for the given duration. It uses the `ffmpeg` tool to create the clip with
    minimal processing and saves it to a designated temporary directory. If a clip with the same
    parameters already exists, it will be reused unless the `forcedownload` parameter is set to True.

    Parameters:
        video_id (str): A unique identifier for the video. Used to generate the filenames.
        mp4 (str): The path to the source video file.
        offset (float): The starting point of the clip in seconds.
        duration (float): The duration of the clip in seconds.
        forcedownload (bool): Whether to force the creation of the clip even if it already
            exists in the destination. Defaults to False.

    Returns:
        str: The path to the generated clip file if successful, or False if the process
            failed.
    """
    dest_file = f"{TMP}/{video_id}_clip.mp4"
    source_file = f"{TMP}/{video_id}.mp4"
    if not os.path.exists(source_file):
        print('source file doesnt exist :(')

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
    """
    Determine the duration of a video file in seconds.

    This function uses ffprobe to fetch the duration of a video file. It first
    checks whether a local file with the video ID exists. If the file exists,
    it uses the local file; otherwise, it uses the provided MP4 file path. The
    duration is read in seconds as a floating-point number. If the duration cannot
    be determined, the function returns None.

    Arguments:
        video_id: str
            The unique identifier of the video, used to locate the local video
            clip file.
        mp4: str
            The file path or URL to the MP4 video file.

    Returns:
        float:
            The duration of the video in seconds, or None if the duration could
            not be determined.
    """
    local_file = f"{TMP}/{video_id}_clip.mp4"

    src = local_file if os.path.exists(local_file) else mp4

    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {src}"

    result = os.popen(cmd).read().strip()

    return float(result) if result else None


def generate_clip_and_write_to_s3(
        video: Dict, duration: float, forcedownload: bool = False, offset="auto"
):
    """
        Generates a video clip with a specified duration and uploads it to an S3 bucket.

        The function generates a clip from a given video, which is either already
        present in an S3 bucket or available locally. If the clip already exists
        in the S3 bucket and forced download is not specified, the function avoids
        clip regeneration. Otherwise, it extracts a clip from the source video
        starting from a determined offset, uploads the clip to the S3 bucket, and
        updates the video metadata with the clip's accessible S3 URL.

        Arguments:
        video (Dict): A dictionary representing the video metadata, such as its ID
            and other properties. Includes keys such as 'id' (str), 'mp4' (str, URL
            or path to the video file), and potentially 'mp4_length' (float, the
            video length in seconds).
        duration (float): The desired length of the clip in seconds.
        forcedownload (bool, optional): If True, forces re-download or re-generation
            of the video clip, even when it already exists. Defaults to False.
        offset (Union[str, float], optional): The starting point for the clip, in seconds.
            If set to "auto", the function automatically calculates the offset as the
            midpoint of the video minus half the clip duration. Defaults to "auto".

        Returns:
        Union[Dict, bool]: When successful, returns the updated video dictionary with
            the 'mp4_clip' key containing the URL to the uploaded clip. If the process
            fails, returns False.
    """
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

        if "mp4_length" not in video:
            print('no mp4_length')
            video_length = _get_video_length(video_id, mp4)
            if video_length:
                print('video length', video_length)
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

        return video
    print("clip gen failed with no video exists?")
    return False


def lookup_video_overrides(video):
    """
    Looks up and applies override configurations to the given video object if
    available. The function checks for the existence of a specific configuration
    file and updates the video properties if corresponding overrides are found in
    the file.

    Arguments:
        video (dict): A dictionary representing the video object. Must contain
        an "id" key with a string value.

    Returns:
        dict: The updated video object with applied overrides, if any were found.

    Raises:
        KeyError: If "id" key is missing from the video dictionary.
    """

    video_id = video["id"]
    OVERRIDES_CONFIG = "config/clip_overrides.json"
    if os.path.exists(OVERRIDES_CONFIG):
        with open(OVERRIDES_CONFIG, encoding="utf-8") as f:
            overrides = json.loads(f.read())
            if video_id in overrides:
                video.update(overrides[video_id])

    return video


# START CLIPS MAIN
def genClipsMain():
    """
    Process and manage video manifest files by generating clips, applying overrides, and updating or removing
    manifest files accordingly. This function interacts with an S3 bucket, reads JSON manifest files, applies
    optional overrides for clip offset and length, generates clips, and then updates the manifest file or
    deletes it if the video does not exist.

    Attributes:
        CLIP_OFFSET (str): Key name for clip offset designation in the video manifest.
        CLIP_LENGTH (str): Key name for clip length designation in the video manifest.

        s3helper (S3Helper): Instance of the S3Helper class initialized with the bucket name to handle S3 operations.
        manifest_folder (str): Name of the folder containing imported video manifest files.

    Raises:
        RuntimeError: Raised in case of errors when opening, reading, or processing the manifest files.
    """
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


# START MAIN
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

    fetch_kvl(args, manifest_folder)  # should generate clip
    fetch_kadist(args, manifest_folder)  # should generate clip
    fetch_external(args, manifest_folder)  # should generate clip
    fetch_kviews(args, manifest_folder)  # should generate clip

    clear_temporary_videos(TMP)
