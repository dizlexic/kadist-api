import glob
import os

from lib.s3helper import S3Helper

bucket_name = "arpedia-dev"

s3helper = S3Helper(bucket_name)

for file in glob.glob("storage/*.png"):
    fname = os.path.basename(file)
    s3helper.put_file(fname, file)
