# -*- coding: utf-8 -*-
from typing import Dict, List, Sequence

import json
import time

from whoosh.fields import *
from whoosh.qparser import MultifieldParser
from whoosh.highlight import WholeFragmenter
from whoosh.filedb.filestore import RamStorage

from app_utils import load_videos

from search_engine import SearchEngine

if __name__ == "__main__":

    kvl, interviews, external_videos = load_videos(
        manifest_folder="imported_videos", suppress_image_data_uri=True
    )

    all_videos = interviews + kvl + external_videos

    schema = Schema(
        id=ID(stored=True, unique=True),
        title=TEXT(stored=True, field_boost=2.0),
        description=NGRAMWORDS(stored=True),
        tags=KEYWORD(stored=True, field_boost=5.0, lowercase=True),
    )

    engine = SearchEngine(schema)
    engine.index_documents(all_videos)

    print(f"indexed {engine.get_index_size()} documents")

    fields_to_search = ["title", "description", "tags"]

    for q in ["Charles Lim", "Bopape", "Changing Room"]:
        print(f"Query:: {q}")
        print("\t", engine.query(q, fields_to_search))
        print("-" * 70)

    print("q=artist", len(engine.query("artist", fields_to_search)))
    print("q=artists", len(engine.query("artists", fields_to_search)))
    print("q=kvl", len(engine.query("kvl", fields_to_search)))
