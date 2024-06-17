# -*- coding: utf-8 -*-
from s3helper import S3Helper

bucket_name = "arpedia-dev"

s3helper = S3Helper(bucket_name)

video_objects = [
    video_object
    for (video_object, _) in s3helper.list_files()
    if "_clip_" not in video_object
]

clip_20s_objects = [
    video_object
    for (video_object, _) in s3helper.list_files()
    if "clip_20s" in video_object
]

clip_10s_objects = [
    video_object
    for (video_object, _) in s3helper.list_files()
    if "clip_10s" in video_object
]


print(
    " *",
    f"{len(video_objects)} video objects, {len(clip_20s_objects)} 20s clips, {len(clip_10s_objects)} 10s clips",
)
