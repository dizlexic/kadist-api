import sys
from s3helper import S3Helper

if __name__ == "__main__":

    s3helper = S3Helper("arpedia-dev")
    for f in s3helper.list_files():
        print(f)
