import hashlib
import json
import re

import requests
import requests_cache
import yaml
from bs4 import BeautifulSoup
from tqdm import tqdm

etl_headers = {}

session = requests_cache.CachedSession(
    cache_name="storage/caches/kview_cache", backend="sqlite", expire_after=60 * 60 * 24 * 7
)  # expire_after 7 days


def remove_tags(text):

    TAG_RE = re.compile(r"<[^>]+>")
    ENTITY_RE = re.compile(r"\&[^;]+;")

    return re.sub(" +", " ", ENTITY_RE.sub(" ", TAG_RE.sub("", str(text)))).strip()


def get_kview_videos():
    with open("../../storage/config/kview_videos.json") as f:
        return json.loads(f.read())


def source_container_pages():
    with open("../../storage/config/kview_scrape_pages.yaml") as f:
        return [x for x in yaml.safe_load(f.read()) if x]


def scrape_videos(source_pages):
    videos = []

    for url in tqdm(source_pages):
        r = session.get(url)

        if r.status_code == requests.codes.ok:
            html = r.content
            soup = BeautifulSoup(html, "html.parser")

            region = "All"

            # remove unused tags
            for elem in soup.findAll(["script", "aside"]):
                elem.extract()

            artist = soup.select("h1", {"class": "article-title"})[0].text.strip()

            video = {"permalink": url, "title": f"60 Seconds with {artist}", "region": region,
                     "description": remove_tags(
                         str(soup.select("p", class_="ap-text-clip")[0]).strip()
                     )}

            try:
                html5_video_tag = soup.findAll("source", type="video/mp4")[0]
            except IndexError:
                print(f"No video for {url}")
                continue

            video["video_url"] = (
                html5_video_tag.get("src").strip()
            )

            if html5_video_tag.has_attr('poster'):
                video["image_url"] = html5_video_tag.get("poster").strip()
            else:
                video["image_url"] = "https://s3.amazonaws.com/arpedia/" + hashlib.md5(video["video_url"].encode("utf8")).hexdigest() + ".jpg"
                r = requests.head(video["image_url"])
                if not r.status_code == requests.codes.ok:
                    print("failed to find poster image", video["image_url"])
                    video["image_url"] = "https://s3.amazonaws.com/arpedia/sixty_seconds.png"

                video["image_width"] = 350
                video["image_height"] = 218


            videos.append(video)

    if videos:
        with open("../../storage/config/kview_videos.json", "w") as f:
            f.write(json.dumps(videos, indent=2, ensure_ascii=False))
            return videos

    return videos


if __name__ == "__main__":
    source_pages = source_container_pages()
    print(" *", f"source pages to scrape: {len(source_pages)} source_pages")
    videos = scrape_videos(source_pages)
    print(" *", f"written {len(videos)} videos")
