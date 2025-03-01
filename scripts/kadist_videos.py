import json
import re
import time
from html import unescape

import requests
import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

etl_headers = {}

session = requests_cache.CachedSession(
    cache_name="caches/kadist_cache", backend="sqlite", expire_after=60 * 60 * 24 * 7
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
    """
    Generate a list of videos from the Kadist website for multiple regions and pages.

    This function fetches video data from the Kadist organization's website by iterating
    through specified regions and pages of the website. It extracts useful information
    about videos, such as permalink, title, region, image details, description, raw video
    URL (if available), and saves the collected data into a JSON file. The function uses a
    requests session and BeautifulSoup for making HTTP requests and parsing HTML content.

    Parameters:
        pages (int): The number of pages to iterate for each region. Default is 15.

    Raises:
        N/A

    Returns:
        None
    """
    videos = []

    regions = [
        ("Europe", "europe-russia"),
        ("North America", "north-america"),
        ("Middle East & Africa", "middle-east-africa"),
        ("Americas", "americas"),
        ("Asia", "asia"),
    ]

    failed_requests = 0
    for n in tqdm(list(range(1, pages + 1))):
        for (region, region_url_fragment) in tqdm(regions, leave=False):
            url = (
                f"https://kadist.org/region/{region_url_fragment}/page/%d/?post_type=program"
                % n
            )
            time.time()
            r = session.get(url)

            if r.status_code == requests.codes.ok:
                html = r.content
                soup = BeautifulSoup(html, "html.parser")

                # remove unused tags
                for elem in soup.findAll(["script", "aside"]):
                    elem.extract()

                for div in soup.findAll("div", {"class": "teaser-videos"}):

                    url = (
                        div.select("a.teaser-content-title")[0]["href"]
                    )

                    video = {
                        "permalink": url,
                        "title": div.select("span.the-title")[0].text.strip(),
                        "region": region,
                    }

                    if div.select(".teaser-image-wrap img"):
                        video["image_url"] = div.select(".teaser-image-wrap img")[0][
                            "src"
                        ]
                        video["image_width"] = div.select(".teaser-image-wrap img")[0][
                            "width"
                        ]
                        video["image_height"] = div.select(".teaser-image-wrap img")[0][
                            "height"
                        ]

                    time.time()
                    r = session.get(url, headers=etl_headers)
                    if r.status_code == requests.codes.ok:
                        html = r.content.decode("utf-8")
                        soup = BeautifulSoup(html, "html.parser")
                        # grab the description from the text
                        if soup.select("div.article-body-text p"):
                            video["description"] = remove_tags(
                                str(soup.select("div.article-body-text p")[0])
                            )
                        else:
                            video["description"] = ""

                        # grab the iframe URL for the vimeo page
                        try:
                            src = soup.select("iframe")[0]["src"]
                        except IndexError:
                            print(f"No video found for {url} - skipping")
                            continue

                        if "vimeo" in src:

                            if soup.select("iframe"):
                                video_url = (
                                    "https:"
                                    + unescape(soup.select("iframe")[0]["src"].strip())
                                    + "&transparent=0&autoplay=1&loop=1&autopause=0"
                                )

                                # resolve redirect link
                                time.time()
                                r = requests.get(video_url, headers=etl_headers)

                                if r.status_code == requests.codes.ok:
                                    html = r.content.decode("utf-8")
                                    video_soup = BeautifulSoup(html, "html.parser")
                                    if video_soup.select("head link"):

                                        if video_soup.select("link")[0].has_attr(
                                            "href"
                                        ):
                                            video["raw_video_url"] = video_soup.select(
                                                "link"
                                            )[0]["href"]
                                            videos.append(video)

            else:
                print("failed request")
                failed_requests = failed_requests + 1
                if failed_requests > 5:
                    print("failed total > limit", failed_requests)
                    break


    if videos:
        output_file = "config/kadist_videos.json"
        with open(output_file, "w") as f:
            f.write(json.dumps(videos, indent=2, ensure_ascii=False))
            print(f" * written {len(videos)} to {output_file}")


if __name__ == "__main__":
    generate_kadist_video_list(pages=100)
