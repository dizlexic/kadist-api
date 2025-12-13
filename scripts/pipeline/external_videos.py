import csv
import html
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Sequence, Union

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cache requests to avoid re-scraping WordPress for the same page during runs.
session = requests_cache.CachedSession(
    cache_name="storage/caches/videos_search_cache",
    backend="sqlite",
    expire_after=60 * 60 * 24 * 7,  # 7 days
)

CSV_PATH = os.path.join(os.getcwd(), "KADIST-Export.csv")
OUTPUT_PATH = os.path.join("storage", "config", "external_videos.json")


def get_wordpress_url(page_id: str) -> str:
    return f"https://kadist.org?page_id={page_id}"


def _safe_text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def scrape_wordpress_page(page_id: str) -> Dict[str, Union[str, List[Dict[str, str]]]]:
    url = get_wordpress_url(page_id)
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
    except Exception as exc:
        print(f" * failed to fetch {url}: {exc}")
        return {
            "permalink": url,
            "title": "",
            "description": "",
            "tags": [],
            "images": [],
            "videos": [],
        }

    soup = BeautifulSoup(r.content, "html.parser")

    title_tag = soup.find("h1") or soup.find("title")
    description_tag = soup.find("meta", {"name": "description"})
    og_desc = soup.find("meta", {"property": "og:description"})
    desc_text = description_tag.get("content", "") if description_tag else ""
    if not desc_text and og_desc:
        desc_text = og_desc.get("content", "")

    # Prefer og:image then first <img>
    images: List[Dict[str, str]] = []
    og_image = soup.find("meta", {"property": "og:image"})
    if og_image and og_image.get("content"):
        images.append({"url": og_image.get("content"), "caption": ""})
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith("http") and all(img.get("src") != i.get("url") for i in images):
            images.append(
                {
                    "url": src,
                    "caption": img.get("alt", ""),
                    "width": img.get("width", ""),
                    "height": img.get("height", ""),
                }
            )

    tags: List[str] = []
    tag_nodes = soup.find_all("meta", {"property": "article:tag"}) or soup.find_all(class_="tag")
    for tag in tag_nodes:
        content = tag.get("content") if tag.name == "meta" else _safe_text(tag)
        if content:
            tags.append(content)

    videos: List[Dict[str, str]] = []
    # look for <source> tags inside <video>
    for video in soup.find_all("video"):
        for source in video.find_all("source"):
            src = source.get("src")
            if src:
                videos.append({"url": src, "type": source.get("type", "")})
    # also look for iframes that might contain mp4/m3u8 links
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src")
        if src and src.startswith("http"):
            videos.append({"url": src, "type": "iframe"})

    return {
        "permalink": url,
        "title": _safe_text(title_tag),
        "description": desc_text,
        "tags": tags,
        "images": images,
        "videos": videos,
    }


def read_csv_rows(csv_path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not os.path.exists(csv_path):
        print(f" * CSV file not found at {csv_path}")
        return rows

    with open(csv_path, "r", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if not row or not row[0].strip():
                continue
            page_id = row[0].strip()
            name = html.unescape(row[1].strip()) if len(row) > 1 else ""
            collection = html.unescape(row[2].strip()) if len(row) > 2 else ""
            video_url = row[3].strip() if len(row) > 3 else ""
            rows.append(
                {
                    "page_id": page_id,
                    "name": name,
                    "collection": collection,
                    "video_url": video_url,
                }
            )
    return rows


def build_video_entry(row: Dict[str, str]) -> Optional[Dict[str, Union[str, Sequence]]]:
    page_id = row.get("page_id", "")
    scraped = scrape_wordpress_page(page_id)

    # merge fields with preference: scraped -> CSV
    entry: Dict[str, Union[str, Sequence]] = {
        "id": page_id,
        "permalink": scraped.get("permalink", get_wordpress_url(page_id)),
        "title": scraped.get("title") or row.get("name", ""),
        "collection": row.get("collection", ""),
        "description": scraped.get("description", ""),
        "tags": scraped.get("tags", []),
        "images": scraped.get("images", []),
    }

    # Prefer CSV video_url, fall back to scraped videos
    csv_video_url = row.get("video_url", "")
    video_url = csv_video_url or None
    if not video_url:
        scraped_videos = scraped.get("videos", []) or []
        if scraped_videos:
            video_url = scraped_videos[0].get("url")
    if not video_url:
        return None

    entry["video_url"] = video_url
    return entry


def write_if_changed(path: str, data: Sequence[Dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_payload = json.dumps(data, indent=2, ensure_ascii=False)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == new_payload:
                print(f" * no changes detected in {path}")
                return
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_payload)
    print(f" * wrote {len(data)} entries to {path}")


def get_external_videos() -> List[str]:
    """Return list of video URLs for downloader compatibility."""
    if not os.path.exists(OUTPUT_PATH):
        return []
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        payload = json.loads(f.read())
    urls: List[str] = []
    for item in payload:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            url = item.get("video_url") or item.get("url")
            if url:
                urls.append(url)
    return urls


def generate_external_video_list(csv_path: str = CSV_PATH) -> List[Dict]:
    rows = read_csv_rows(csv_path)
    if not rows:
        print(" * no rows to process")
        return []

    videos: List[Dict] = []
    seen = set()

    max_workers = min(8, max(1, os.cpu_count() or 2))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(build_video_entry, row): row for row in rows}
        for fut in tqdm(as_completed(futures), total=len(futures)):
            entry = fut.result()
            if not entry:
                continue
            url = entry.get("video_url")
            if url and url not in seen:
                seen.add(url)
                videos.append(entry)

    write_if_changed(OUTPUT_PATH, videos)
    return videos


if __name__ == "__main__":
    videos = generate_external_video_list()
    print(" *", f"processed {len(videos)} entries from CSV")
