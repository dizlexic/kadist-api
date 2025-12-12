import json
import os
import re
import time
from html import unescape

import requests
import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

etl_headers = {}

session = requests_cache.CachedSession(
    cache_name="storage/caches/kadist_cache", backend="sqlite", expire_after=60 * 60 * 24 * 7
)  # expire_after 7 days

# This is literally scraping the html from the website, not the JSON so we aren't getting the new "links" fields (caption, etc)

def remove_tags(text):
    """
    Removes HTML tags and entities from the given text.

    This function takes a string input, strips HTML tags, replaces any
    HTML entities with a space, and collapses multiple spaces into a
    single space. It ensures the output string is clean and readable
    by eliminating unwanted formatting artifacts.

    Args:
        text (str): The input text containing HTML tags and/or entities.

    Returns:
        str: A clean string with HTML tags and entities removed.
    """
    TAG_RE = re.compile(r"<[^>]+>")
    ENTITY_RE = re.compile(r"&[^;]+;")

    return re.sub(" +", " ", ENTITY_RE.sub(" ", TAG_RE.sub("", str(text))))


def save_video(url, path):
    """
    Function to save a video from a given URL to a specified path.

    This function takes a video URL and a file path as arguments,
    and it handles the appropriate process of storing the video content
    to the provided path. It assumes the implementation of downloading
    and saving mechanisms.

    Args:
        url (str): The URL from which the video will be downloaded.
        path (str): The file path where the video will be saved.

    Returns:
        None
    """
    print(" *", f"--> saving ({url}) new video to {path}")


def generate_kadist_video_list(pages=15):
    videos = []

    regions = [
        ("Europe", "europe-russia"),
        ("North America", "north-america"),
        ("Latin America", "latin-america"),
        ("Middle East & Africa", "middle-east-africa"),
        ("Asia", "asia"),
    ]

    failed_requests = 0
    current_page = 1  # Initialize the page counter

    for (region, region_url_fragment) in tqdm(regions, leave=False):
        current_page = 1
        exists = True

        while exists:
            url = (
                    f"https://kadist.org/region/{region_url_fragment}/page/%d/?post_type=program"
                    % current_page
            )
            time.time()
            r = session.get(url)

            if r.status_code == requests.codes.ok:
                html = r.content
                soup = BeautifulSoup(html, "html.parser")

                # remove unused tags
                for elem in soup.find_all(["script", "aside"]):
                    elem.extract()

                # Process teaser items concurrently for detail page fetch
                from concurrent.futures import ThreadPoolExecutor, as_completed

                teaser_divs = soup.find_all("div", {"class": "teaser-videos"})

                def build_item(div):
                    try:
                        u = div.select("a.teaser-content-title")[0]["href"]
                        item = {
                            "permalink": u,
                            "title": div.select("span.the-title")[0].text.strip(),
                            "region": region,
                        }
                        if div.select(".teaser-image-wrap img"):
                            img = div.select(".teaser-image-wrap img")[0]
                            item["image_url"] = img.get("src")
                            item["image_width"] = img.get("width")
                            item["image_height"] = img.get("height")
                        return item
                    except Exception:
                        return None

                def worker(item):
                    if not item:
                        return None
                    url2 = item["permalink"]
                    r2 = session.get(url2, headers=etl_headers)
                    if r2.status_code != requests.codes.ok:
                        return None
                    html2 = r2.content.decode("utf-8")
                    soup2 = BeautifulSoup(html2, "html.parser")
                    if soup2.select("div.article-body-text p"):
                        item["description"] = remove_tags(
                            str(soup2.select("div.article-body-text p")[0])
                        )
                    else:
                        item["description"] = ""

                    try:
                        src = soup2.select("iframe")[0]["src"]
                    except IndexError:
                        print(f"No video for {url2}")
                        return None
                    if "vimeo" not in src:
                        return None
                    video_url = (
                            "https:" + unescape(soup2.select("iframe")[0]["src"].strip()) +
                            "&transparent=0&autoplay=1&loop=1&autopause=0"
                    )
                    r3 = session.get(video_url, headers=etl_headers)
                    if r3.status_code != requests.codes.ok:
                        return None
                    html3 = r3.content.decode("utf-8")
                    video_soup = BeautifulSoup(html3, "html.parser")
                    if video_soup.select("head link") and video_soup.select("link")[0].has_attr("href"):
                        item["raw_video_url"] = video_soup.select("link")[0]["href"]
                        return item
                    return None

                items = [build_item(d) for d in teaser_divs]
                max_workers = 6
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futures = [ex.submit(worker, it) for it in items]
                    for fut in as_completed(futures):
                        res = fut.result()
                        if res:
                            videos.append(res)
            else:
                if r.status_code == 404:
                    print(f" * no more pages in region {region} after page {current_page - 1}")
                    exists = False
            current_page += 1
        # Increment the page counter
    if videos:
        output_file = os.path.join("storage", "config", "kadist_videos.json")
        with open(output_file, "w") as f:
            f.write(json.dumps(videos, indent=2, ensure_ascii=False))
            print(f" * written {len(videos)} to {output_file}")
    else:
        print(" * no videos found")

if __name__ == "__main__":
    print(" *", "starting kadist_videos.py")
    generate_kadist_video_list()
    print(" *", "finished kadist_videos.py")
