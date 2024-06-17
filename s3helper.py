import json
import boto
import os

from dotenv import dotenv_values
from tqdm import tqdm

from boto.s3.key import Key
import boto.s3.connection

from typing import Dict, Sequence, Union


class S3Helper:
    def __init__(self, bucket_name: str, cache_files=True):
        config = dotenv_values(".env")
        if "AWS_ACCESS_KEY_ID" in config and "AWS_SECRET_ACCESS_KEY" in config:
            AWS_ACCESS_KEY_ID = config["AWS_ACCESS_KEY_ID"]
            AWS_SECRET_ACCESS_KEY = config["AWS_SECRET_ACCESS_KEY"]
        elif os.path.exists("keys.secret"):
            with open("keys.secret") as key_file:
                j = json.loads(key_file.read())
                AWS_ACCESS_KEY_ID = j["AccessKeyID"]
                AWS_SECRET_ACCESS_KEY = j["SecretAccessKey"]
        else:
            raise Exception("Missing keys.secret for S3")

        print(" *", "connecting to S3...")
        conn = boto.connect_s3(
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            is_secure=False,
            calling_format=boto.s3.connection.OrdinaryCallingFormat(),
        )

        self.bucket = conn.get_bucket(bucket_name)

        self.cached_bucket_list = False

    def put_file(self, name: str, abspath: str, only_if_modified: bool = True) -> str:
        k = Key(self.bucket)

        if only_if_modified:
            if os.path.exists(abspath):
                size_on_s3 = self.file_size(name)
                if size_on_s3 > 0:
                    if os.path.getsize(abspath) == size_on_s3:
                        # nothing to do, already on s3 and same size
                        print(
                            " *",
                            f"skipping putting {name} on S3 from {abspath}... (already there)",
                        )
                        return

        print(" *", f"putting {name} on S3 from {abspath}...")
        k.key = name

        with tqdm(total=10, leave=False) as pbar:
            k.set_contents_from_filename(
                abspath, num_cb=10, cb=lambda bytes, final_size: pbar.update()
            )

        k.set_acl("public-read")

    def write_json(self, name: str, obj: Union[Dict, Sequence]) -> int:
        k = Key(self.bucket)
        k.key = name

        k.set_contents_from_string(
            json.dumps(obj, indent=2),
            replace=True,
        )

        k.set_acl("public-read")

        return k.size

    def read_json(self, name: str) -> Union[Dict, Sequence]:
        key = self.bucket.get_key(name)
        if key:
            return json.loads(key.read())
        else:
            return None

    def rm_files(self, filenames):
        for key in self.bucket.list():
            if key.name in filenames:
                print(" *", "rm", key.name)
                self.bucket.delete_key(key)

    def file_exists(self, filename):
        return filename in [name for (name, size) in self.list_files()]

    def file_size(self, filename):
        for (name, size) in self.list_files():
            if filename == name:
                return size
        return -1

    def list_files(self):
        if not self.cached_bucket_list:
            self.cached_bucket_list = [
                (key.name, key.size) for key in self.bucket.list()
            ]

        return self.cached_bucket_list
