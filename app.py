import json
import logging
import os
import time

from flask import Flask, request, render_template, Response
from flask_cors import CORS
from flask_restx import Api, Resource, reqparse, inputs
from whoosh.analysis import NgramWordAnalyzer, SimpleAnalyzer
from whoosh.fields import *

from lib.app_utils import (
    load_videos,
    get_popularity,
    increment_popularity,
    suggested_videos,
    get_pinned_videos,
    remove_pin_video,
    add_pin_video,
)
from lib.search_engine import SearchEngine

app = Flask(__name__)
app.config.SWAGGER_UI_DOC_EXPANSION = "list"
app.config.SWAGGER_UI_REQUEST_DURATION = True

cors = CORS(app, resources={r"/ktv_api/*": {"origins": "*"}})

_version_ = "1.5"

api = Api(app=app, version=_version_, title="Kadist TV API")
name_space = api.namespace("ktv_api", description="Kadist TV APIs")

boot_time = time.time()

logging.basicConfig(level=logging.DEBUG)

try:
    kvl_videos, interview_videos, external_videos, kview_videos = load_videos(
        manifest_folder="storage/imported_videos"
    )
except Exception as e:
    logging.error(f"Error loading videos: {e}")
    kvl_videos, interview_videos, external_videos, kview_videos = [], [], [], []

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

valid_videos = [v for v in all_videos if "id" in v and "title" in v]
engine.index_documents(valid_videos)
logging.debug(f"Indexed {len(valid_videos)} videos")

print(" *", f"indexed {engine.get_index_size()} documents")


#
# UI
#


@app.route("/ui")
def ui():
    """
        Handles the "/ui" route, rendering video content as per the query parameters or
        default suggestions. This function fetches and renders the appropriate videos
        based on user input or suggested video sources.

        Sections:
        - If a query parameter 'q' is provided, it fetches videos matching the query using
          a search engine and includes their titles, descriptions, and tags.
        - If no query parameter is provided, it retrieves suggested videos from predefined
          sources and renders them.

        Args:
        q: Optional[str]
            The query string to search for videos using the search engine.

        Returns:
        Response
            A Flask Response object containing the rendered video content in text/html
            format, along with HTTP 200 status.
    """
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
        render_template("views/ui.html", title="Kadist TV", videos=videos),
        status=200,
        mimetype="text/html",
    )


#
# Admin Interface
#


@app.route("/admin")
def admin():
    """
        Generates and returns the admin page with relevant data.

        The function is responsible for compiling data to be displayed on the admin
        page by retrieving, filtering, and sorting the popularity of specific videos.
        It also fetches pinned videos and categorizes them for rendering on the
        page. The rendered HTML page is returned with an HTTP 200 status.

        @return: Instance of `Response` containing the rendered admin page and its
                 associated status and MIME type.
    """
    popularity = {k: v for k, v in get_popularity().items() if k in index}
    sorted_videos = sorted(popularity.items(), key=lambda v: v[1], reverse=True)
    pinned_videos = get_pinned_videos()

    return Response(
        render_template(
            "views/admin.html",
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
    """
    Handles the API endpoint for retrieving the uptime of the Kadist TV
    service.

    This class defines a RESTful resource API to fetch uptime details
    for the Kadist TV service, including the current version and the
    service's uptime in seconds.

    Attributes:
        None

    """
    def get(self):
        return {
            "version": _version_,
            "uptime_s": time.time() - boot_time,
        }


@name_space.route("/suggested_videos")
@api.doc(params={"count": "(int) how many videos, defaults 16"})
class KadistTVSuggestedVideosAPI(Resource):
    """
    KadistTVSuggestedVideosAPI provides an API endpoint to fetch a list of suggested
    videos with a customizable count.

    This class is designed to handle GET HTTP requests and returns a list of
    suggested videos in JSON format. It uses a default count of 16 videos unless
    specified otherwise by the user.

    Attributes:
        None

    Methods:
        None
    """
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument("count", type=int, default=16, location='args')
        args = parser.parse_args()

        data = {
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

        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )


@name_space.route("/all_videos")
@api.doc(params={"kvl_videos": "(bool) include kvl videos"})
@api.doc(params={"interview_videos": "(bool) include the interview videos"})
@api.doc(params={"external_videos": "(bool) include the external videos"})
@api.doc(params={"kview_videos": "(bool) include the external videos"})
class KadistTVAllVideosAPI(Resource):
    """
    Handles the retrieval of all videos available across different categories.

    This class is part of a REST API that manages the retrieval of various video types
    including KVL videos, interview videos, external videos, and KView videos. It offers
    a GET endpoint where users can specify which types of videos to include in the result
    via query string parameters. The API aggregates the specified video categories and
    returns the aggregated result along with the total number of available videos.

    Attributes:
        kvl_videos (bool): Corresponds to including KVL videos in the response.
        interview_videos (bool): Corresponds to including interview videos in the response.
        external_videos (bool): Corresponds to including external videos in the response.
        kview_videos (bool): Corresponds to including KView videos in the response.
    """
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

        data = {"videos": d, "total_available_videos": len(all_videos)}
        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )


@name_space.route("/pin")
class KadistTVPingAPI(Resource):
    """
    Handles the API endpoint for retrieving pinned videos.

    This class is part of an API implementation using Flask-RESTful. It is
    responsible for responding to GET requests made to the '/pin' route. The
    purpose of this class is to return a JSON list of pinned videos from the
    dataset or service it integrates with. The response is formatted in JSON
    with an HTTP status 200 and appropriate settings.

    """
    def get(self):
        return Response(
            json.dumps(get_pinned_videos(), indent=2, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )


@name_space.route("/pin/<video_id>")
class KadistTVWatchedAPI(Resource):
    """
    Represents an API endpoint for managing pinned videos.

    This class provides functionality to add or remove a video to/from the list
    of pinned videos. It interacts with an external system to check the current
    state of pinned videos and perform the appropriate actions.

    Methods:
        post: Handles HTTP POST requests to pin a video.
        delete: Handles HTTP DELETE requests to unpin a video.
    """
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
    """KadistTVStatsAPI class provides API endpoint for retrieving Kadist TV statistics.

    This class represents a RESTful API resource that manages and retrieves data regarding
    popularity statistics for Kadist TV. It is designed to handle HTTP GET requests and
    respond with the relevant data.

    Attributes:
        None

    Methods:
        get():
            Handles GET requests and returns Kadist TV popularity statistics.
    """
    def get(self):
        return get_popularity()


@name_space.route("/watched/<video_id>")
class KadistTVWatchedAPI(Resource):
    """
    Handles marking a video as watched and updating its popularity index.

    This class includes functionality to process API requests for marking
    videos as watched. It verifies if the video exists in the index and
    updates its popularity if found. Otherwise, it returns a failure response.

    Raises:
        KeyError: Raised when the video ID does not exist in the index if the
        implementation depends on further key validations.

    Methods:
        post(video_id: str): Handles the POST request for marking a video
        as watched and updating its popularity.
    """
    def post(self, video_id: str):
        if video_id in index:
            return increment_popularity(video_id)
        else:
            return False


@name_space.route("/search")
@api.doc(params={"q": "search query"})
@api.doc(params={"highlight_results": "(bool) highlight html"})
class KadistTVSearchAPI(Resource):
    """
    Provides an API endpoint to perform search queries on Kadist TV.

    The KadistTVSearchAPI class is implemented as a RESTful resource that allows users to
    execute search queries with optional highlighted HTML results. The class handles the
    request, parses the provided query parameters, performs the search, and responds
    with relevant search results in JSON format.

    Attributes:
        None
    """
    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument("q", location='args')
        parser.add_argument("highlight_results", type=inputs.boolean, default=False, location='args')
        args = parser.parse_args()

        logging.info(f" * KadistTVSearchAPI, [q: {args.q}]")

        results = engine.query(
            args.q, ["title", "description", "tags"], highlight=args.highlight_results
        )

        data = {
            "count": results["size"],
            "q": results["q"],
            "searching_in": results["search_in_fields"],
            "time_s": results["time"],
            "results": results["hits"],
        }

        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )


if __name__ == "__main__":
    logging.info(" * server starting")
    env = os.environ.get('KTV_ENV') or 'development'

    try:
        port = int(os.environ.get('API_PORT', 1337))
    except ValueError:
        port = 1337

    app.run(host="0.0.0.0", debug=True, port=port)
