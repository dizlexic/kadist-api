import os

from flask import Flask, request, render_template, Request, Response

from flask_restx import Api, Resource, reqparse, inputs

from flask_cors import CORS

import logging
import json
import time

from whoosh.fields import *
from whoosh.analysis import NgramWordAnalyzer, SimpleAnalyzer

from app_utils import (
    load_videos,
    get_popularity,
    increment_popularity,
    suggested_videos,
    get_pinned_videos,
    remove_pin_video,
    add_pin_video,
)

from search_engine import SearchEngine

app = Flask(__name__)
app.config.SWAGGER_UI_DOC_EXPANSION = "list"
app.config.SWAGGER_UI_REQUEST_DURATION = True

cors = CORS(app, resources={r"/ktv_api/*": {"origins": "*"}})

_version_ = "1.5"

api = Api(app=app, version=_version_, title="Kadist TV API")
name_space = api.namespace("ktv_api", description="Kadist TV APIs")

boot_time = time.time()

logging.basicConfig(level=logging.DEBUG)

kvl_videos, interview_videos, external_videos, kview_videos = load_videos(
    manifest_folder="imported_videos"
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


#
# UI
#


@app.route("/ui")
def ui():

    q = request.args.get("q")

    if q:
        videos = engine.query(q, ["title", "description", "tags"], highlight=False)[
            "hits"
        ]
    else:
        videos = suggested_videos(
            index, interview_videos, kvl_videos, external_videos, 9
        )

    return Response(
        render_template("ui.html", title="Kadist TV", videos=videos),
        status=200,
        mimetype="text/html",
    )


#
# Admin Interface
#


@app.route("/admin")
def admin():
    popularity = {k: v for k, v in get_popularity().items() if k in index}
    sorted_videos = sorted(popularity.items(), key=lambda v: v[1], reverse=True)
    pinned_videos = get_pinned_videos()

    return Response(
        render_template(
            "admin.html",
            sorted_videos=sorted_videos,
            index=index,
            interview_videos=interview_videos,
            kvl_videos=kvl_videos,
            external_videos=external_videos,
            kview_videos=kview_videos,
            pinned_videos=pinned_videos,
        ),
        status=200,
        mimetype="text/html",
    )


@name_space.route("/uptime")
class KadistTVUptimeAPI(Resource):
    def get(self):

        return {
            "version": _version_,
            "uptime_s": time.time() - boot_time,
        }


@name_space.route("/suggested_videos")
@api.doc(params={"count": "(int) how many videos, defaults 16"})
class KadistTVSuggestedVideosAPI(Resource):
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument("count", type=int, default=16, location='args')
        args = parser.parse_args()

        return {
            "count": args.count,
            "videos": suggested_videos(
                index,
                interview_videos,
                kvl_videos,
                external_videos,
                kview_videos,
                args.count,
            ),
        }


@name_space.route("/all_videos")
@api.doc(params={"kvl_videos": "(bool) include kvl videos"})
@api.doc(params={"interview_videos": "(bool) include the interview videos"})
@api.doc(params={"external_videos": "(bool) include the external videos"})
@api.doc(params={"kview_videos": "(bool) include the external videos"})
class KadistTVAllVideosAPI(Resource):
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument("kvl_videos", type=inputs.boolean, default=True, location='args')
        parser.add_argument("interview_videos", type=inputs.boolean, default=True, location='args')
        parser.add_argument("external_videos", type=inputs.boolean, default=True, location='args')
        parser.add_argument("kview_videos", type=inputs.boolean, default=True, location='args')
        args = parser.parse_args()

        d = {}

        if args.kvl_videos:
            d["kvl_videos"] = kvl_videos

        if args.interview_videos:
            d["interview_videos"] = interview_videos

        if args.external_videos:
            d["external_videos"] = external_videos

        if args.kview_videos:
            d["kview_videos"] = kview_videos

        return {"videos": d, "total_available_videos": len(all_videos)}


@name_space.route("/pin")
class KadistTVPingAPI(Resource):
    def get(self):
        return get_pinned_videos()


@name_space.route("/pin/<video_id>")
class KadistTVWatchedAPI(Resource):
    def post(self, video_id: str):
        if video_id in index and not video_id in get_pinned_videos():
            return add_pin_video(video_id)
        else:
            return False

    def delete(self, video_id: str):
        if video_id in get_pinned_videos():
            return remove_pin_video(video_id)
        else:
            return False


@name_space.route("/stats")
class KadistTVStatsAPI(Resource):
    def get(self):
        return get_popularity()


@name_space.route("/watched/<video_id>")
class KadistTVWatchedAPI(Resource):
    def post(self, video_id: str):
        if video_id in index:
            return increment_popularity(video_id)
        else:
            return False


@name_space.route("/search")
@api.doc(params={"q": "search query"})
@api.doc(params={"highlight_results": "(bool) highlight html"})
class KadistTVSearchAPI(Resource):
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument("q", location='args')
        parser.add_argument("highlight_results", type=inputs.boolean, default=False, location='args')
        args = parser.parse_args()

        logging.info(f" * KadistTVSearchAPI, [q: {args.q}]")

        results = engine.query(
            args.q, ["title", "description", "tags"], highlight=args.highlight_results
        )

        return {
            "count": results["size"],
            "q": results["q"],
            "searching_in": results["search_in_fields"],
            "time_s": results["time"],
            "results": results["hits"],
        }


if __name__ == "__main__":
    logging.info(" * server starting")
    env = os.environ.get('KTV_ENV') or 'development'
    port = int(os.environ.get('TV_API_PORT') or 5000)
    app.run(host="0.0.0.0", debug=True, port=port)
