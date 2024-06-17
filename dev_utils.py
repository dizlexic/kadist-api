# -*- coding: utf-8 -*-
from typing import List, Sequence

import requests
import requests_cache

import PIL

from PIL import Image, ImageFile

from io import BytesIO
import base64


from tempfile import NamedTemporaryFile

import urllib3
import argparse

ImageFile.LOAD_TRUNCATED_IMAGES = True

urllib3.disable_warnings()

requests_cache.CachedSession(
    cache_name="poster_cache", backend="sqlite", expire_after=60 * 96
)  # minutes


def str2bool(v: str):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


# order preserving duplicate string removal from sequence
def f7(seq: Sequence[str]) -> List[str]:
    if seq:
        seen = set()
        seen_add = seen.add
        return [x for x in seq if x and not (x.lower() in seen or seen_add(x.lower()))]
    else:
        return []


def download_video_file(url):
    print("download_video_file", url)
    with requests.get(url, stream=True, headers={"referer": "http://kadist.org/"}) as r:
        r.raise_for_status()
        with NamedTemporaryFile(
            prefix="video_", suffix=f".{url.split('.')[-1]}", delete=False
        ) as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

    return f.name


def image_url_to_data_uri(imgurl: str):
    max_size = 400, 400
    with requests.get(imgurl.strip(), timeout=60, verify=False, stream=True) as r:
        r.raise_for_status()
        buffer = BytesIO()

        img = Image.open(BytesIO(r.content))
        img.thumbnail(max_size, PIL.Image.LANCZOS)
        img.convert("RGB").save(buffer, format="PNG", optimize=True, quality=90)

        buffer.seek(0)
        data64 = "".join(base64.b64encode(buffer.read()).decode("utf-8").splitlines())
        return f"data:image/png;base64,{data64}"


