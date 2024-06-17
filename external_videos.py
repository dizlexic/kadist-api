import json
import random
import time

import requests
import requests_cache
from tqdm import tqdm
from youtubesearchpython import VideosSearch

requests_cache.CachedSession(
    cache_name="videos_search_cache", backend="sqlite", expire_after=60 * 60 * 24 * 7
)  # expire_after in seconds


MAX_VIDEOS_PER_SEARCH = 1

VIDEO_DEFAULT_LINKS = [
    "https://www.youtube.com/watch?v=vTnmO6UXFUc",
    "https://www.youtube.com/watch?v=L_gAQNuDUOo",
    "https://www.youtube.com/watch?v=0bFZ4gcsAPA",
    "https://www.youtube.com/watch?v=6A-GKr1vRE0",
    "https://www.youtube.com/watch?v=TBjM7gKblWU",
    "https://www.youtube.com/watch?v=1ELmm-jNkLs",
    "https://www.youtube.com/watch?v=ou2Ipfy3f2E",
    "https://www.youtube.com/watch?v=yDapK6Vj4Fo",
    "https://www.youtube.com/watch?v=VELZDdxcuxU",
    "https://www.youtube.com/watch?v=KWkhXCFq-C4",
    "https://www.youtube.com/watch?v=0ZZn7_44_B4",
    "https://www.youtube.com/watch?v=T-Av2XKJ16A",
    "https://www.youtube.com/watch?v=zk5uh1uV3jA",
    "https://www.youtube.com/watch?v=TdgyX3cwZy4",
    "https://www.youtube.com/watch?v=JEvT0c5NaLQ",
    "https://www.youtube.com/watch?v=CATey5LcEF4",
    "https://www.youtube.com/watch?v=fEsPdNEKYAE",
]

VIDEO_SEARCH_ERRATA = [
    "Ketchup Session",
    "Magalí Arriola",
    "Pável Aguilar",
    "Carlos Amorales",
    "Edgardo Aragón",
    "Jorge Julián Aristizábal",
    "Adriana Bustos",
    "Fredi Casco",
    "Rometti Costales",
    "Aria Dean",
    "Sam Durant",
    "Pierre Huyghe",
    "Cristóbal Lehyt",
    "Jesse Lerner",
    "Alfredo López Morales",
    "Noé Martinez",
    "Cildo Meireles",
    "Eustáquio Neves Juatuba",
    "Nohemí Pérez",
    "Naufus Ramírez Figueroa",
    "Carla Zaccagnini",
    "Iheanyi Onwuegbucha",
    "El Anatsui",
    "Ntshepe Tsekere Bopape",
    "Nidhal Chamekh",
    "Bady Dalloul",
    "Rahima Gambo",
    "Goddy Leye",
    "Abraham Oghobase",
    "Wura-Natasha Ogunji",
    "Chloé Quenum",
    "Abraham Oghobase",
    "Nidhal Chamekh",
    "Fanny Souade Sow",
]


def get_external_videos():
    """get a list of youtube URLs, only the link is returned."""

    with open("config_files/external_videos.json") as f:
        return [x for x in set(json.loads(f.read()))]


def search_youtube_by_keyword(
    artist_name, min_view_count, max_videos_per_search=MAX_VIDEOS_PER_SEARCH
):
    """returns only the video link"""

    vs = VideosSearch(f"{artist_name} artist", limit=max_videos_per_search)
    for result in vs.result()["result"]:
        result["title"]
        if "type" in result and result["type"] == "video":
            if result["viewCount"]["text"]:
                view_count_chars = "".join(
                    [i for i in result["viewCount"]["text"] if i.isdigit()]
                )
                view_count = int(view_count_chars) if view_count_chars else 0
                if view_count >= view_count:
                    return result["link"]


def generate_external_video_list(min_view_count, include_search=True):
    """For each Kadist artist search Youtube for video"""
    arpedia_url = "https://arpedia.herokuapp.com/arpedia/v1/kadist_artists?only_include_artist_names=true"
    r = requests.get(arpedia_url)
    if r.status_code == requests.codes.ok:
        kadist_artists = r.json()["result"]

        videos = VIDEO_DEFAULT_LINKS

        if include_search:
            all_artists = set(kadist_artists + VIDEO_SEARCH_ERRATA)

            # reduced set, remove for all yt content
            # all_artists = set(VIDEO_SEARCH_ERRATA)

            for artist_name in tqdm(all_artists):

                time.sleep(0.1 + random.randint(10, 35) / 100)

                video_link = search_youtube_by_keyword(artist_name, min_view_count)
                if video_link and video_link not in videos:
                    videos.append(video_link)

        if videos:
            with open("config_files/external_videos.json", "w") as f:
                f.write(json.dumps(videos, indent=2, ensure_ascii=False))
                return videos


if __name__ == "__main__":
    videos = generate_external_video_list(min_view_count=50, include_search=True)
    print(" *", f"written {len(videos)} videos")
