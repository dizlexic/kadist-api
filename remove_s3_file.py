import sys
from s3helper import S3Helper

if __name__ == "__main__":

    s3helper = S3Helper("arpedia-dev")

    for f in sys.argv[1:]:
        if s3helper.file_exists(f):
            s3helper.rm_files([f])
        else:
            print(f"{f} does not exist on s3")
