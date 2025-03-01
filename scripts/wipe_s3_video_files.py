# -*- coding: utf-8 -*-
from lib.s3helper import S3Helper

bucket_name = "arpedia-dev"

s3helper = S3Helper(bucket_name)
mp4_objects = [video_object for (video_object, _) in s3helper.list_files()]

print(" *", f"wiping: {len(mp4_objects)} video objects")

s3helper.rm_files(mp4_objects)

mp4_objects = [video_object for (video_object, _) in s3helper.list_files()]
print(" *", f"after: {len(mp4_objects)} video objects")
