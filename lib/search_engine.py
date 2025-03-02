import json
import logging
import time
from typing import Sequence, Any

from whoosh.filedb.filestore import RamStorage
from whoosh.highlight import WholeFragmenter
from whoosh.qparser import MultifieldParser

from .app_utils import load_videos


class SearchEngine:
    def __init__(self, schema):
        schema.add("raw", STORED())
        self.schema = schema
        self.ix = RamStorage().create_index(schema)

    def index_documents(self, docs: Sequence):
        writer = self.ix.writer()
        for doc in docs:
            d = {k: v for k, v in doc.items() if k in self.schema.stored_names()}
            d["raw"] = json.dumps(doc)  # raw version of all of doc
            writer.add_document(**d)
        writer.commit(optimize=True)

    def get_index_size(self) -> int:
        return self.ix.doc_count_all()

    def query(self, q: str, search_in_fields: Sequence, highlight=True) -> dict[
        str, list[Any] | str | Sequence | float | int]:
        start = time.time()
        search_results = []
        with self.ix.searcher() as searcher:
            results = searcher.search(
                MultifieldParser(search_in_fields, schema=self.schema).parse(q),
                limit=500,
            )

            results.fragmenter = WholeFragmenter(charlimit=100000)

            for hit in results:
                d = json.loads(hit["raw"])
                if highlight:
                    d["title"] = hit.highlights("title") or d["title"]
                    d["description"] = hit.highlights("description") or d["description"]
                search_results.append(d)

        return {
            "time": time.time() - start,
            "q": q,
            "size": len(search_results),
            "search_in_fields": search_in_fields,
            "hits": search_results,
        }


if __name__ == "__main__":
    #
    # just here for debugging search problems
    #
    #

    logging.basicConfig(level=logging.DEBUG)

    from whoosh.fields import *
    from whoosh.analysis import NgramWordAnalyzer, SimpleAnalyzer

    kvl_videos, interview_videos, external_videos, kview_videos = load_videos(
        manifest_folder="storage/imported_videos"
    )

    all_videos = interview_videos + kvl_videos + external_videos + kview_videos
    index = {v["id"]: v for v in all_videos}

    engine = SearchEngine(
        Schema(
            id=ID(stored=True, unique=True),
            title=TEXT(stored=True, field_boost=2.0, analyzer=SimpleAnalyzer()),
            description=TEXT(stored=True, analyzer=NgramWordAnalyzer(minsize=3)),
            tags=KEYWORD(stored=True, field_boost=5.0, lowercase=True),
        )
    )

    print(" *", f"indexing {len(all_videos)} videos...")

    engine.index_documents(all_videos)

    print(" *", f"indexed {engine.get_index_size()} documents")

    results = engine.query(
        "narrative discourse", ["title", "description", "tags"], highlight=False
    )

    print(
        json.dumps(
            [{"title": x["title"], "type": x["type"]} for x in results["hits"]],
            indent=2,
            ensure_ascii=False,
        )
    )
