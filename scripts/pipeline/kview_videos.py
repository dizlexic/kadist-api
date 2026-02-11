import hashlib
import json
import os
import re
import sys

import requests
import yaml
from bs4 import BeautifulSoup
from tqdm import tqdm

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from lib.app_utils import get_robust_session

etl_headers = {}

session = get_robust_session(
    cache_name="storage/caches/kview_cache", expire_after=60 * 60 * 24 * 7
)  # expire_after 7 days


def remove_tags(text):

    TAG_RE = re.compile(r"<[^>]+>")
    ENTITY_RE = re.compile(r"\&[^;]+;")

    return re.sub(" +", " ", ENTITY_RE.sub(" ", TAG_RE.sub("", str(text)))).strip()


def get_kview_videos():
    with open("storage/config/kview_videos.json") as f:
        return json.loads(f.read())


def source_container_pages():
    with open("storage/config/kview_scrape_pages.yaml") as f:
        return [x for x in yaml.safe_load(f.read()) if x]


def scrape_videos(source_pages):
    videos = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def worker(url: str):
        r = session.get(url)
        if r.status_code != requests.codes.ok:
            return None
        html = r.content
        soup = BeautifulSoup(html, "html.parser")

        region = "All"

        # remove unused tags
        for elem in soup.find_all(["script", "aside"]):
            elem.extract()

        artist = soup.select("h1", {"class": "article-title"})[0].text.strip()

        video = {"permalink": url, "title": f"60 Seconds with {artist}", "region": region,
                 "description": remove_tags(
                     str(soup.select("p", class_="ap-text-clip")[0]).strip()
                 )}

        try:
            html5_video_tag = soup.find_all("source", type="video/mp4")[0]
        except IndexError:
            print(f"No video for {url}")
            return None

        video["video_url"] = (
            html5_video_tag.get("src").strip()
        )

        if html5_video_tag.has_attr('poster'):
            video["image_url"] = html5_video_tag.get("poster").strip()
        else:
            video["image_url"] = "https://s3.amazonaws.com/arpedia/" + hashlib.md5(
                video["video_url"].encode("utf8")).hexdigest() + ".jpg"
            r2 = session.head(video["image_url"])
            if not r2.status_code == requests.codes.ok:
                video["image_url"] = "https://s3.amazonaws.com/arpedia/sixty_seconds.png"

            video["image_width"] = 350
            video["image_height"] = 218

        return video

    max_workers = 6
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(worker, url) for url in source_pages]
        for fut in tqdm(as_completed(futures), total=len(futures)):
            result = fut.result()
            if result:
                videos.append(result)

    if videos:
        with open("storage/config/kview_videos.json", "w") as f:
            f.write(json.dumps(videos, indent=2, ensure_ascii=False))
            return videos

    return videos


if __name__ == "__main__":
    print(" *", "starting kview_videos.py")
    source_pages = source_container_pages()
    videos = scrape_videos(source_pages)
    print(" *", "finished kview_videos.py")
