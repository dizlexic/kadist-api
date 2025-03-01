import json
import os
from typing import Dict, Sequence, Union

import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from dotenv import dotenv_values


class S3Helper:
    def __init__(self, bucket_name: str, cache_files=True):
        # Load credentials from .env
        config = dotenv_values(".env")
        if "AWS_ACCESS_KEY_ID" in config and "AWS_SECRET_ACCESS_KEY" in config:
            AWS_ACCESS_KEY_ID = config["AWS_ACCESS_KEY_ID"]
            AWS_SECRET_ACCESS_KEY = config["AWS_SECRET_ACCESS_KEY"]
        else:
            raise Exception("Missing AWS credentials in .env file.")

        # Establish connection to S3
        print(" *", "connecting to S3...")
        try:
            self.s3 = boto3.resource(
                "s3",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            )
            self.bucket = self.s3.Bucket(bucket_name)
        except (NoCredentialsError, PartialCredentialsError) as e:
            raise Exception(f"Failed to connect to S3: {str(e)}")

        self.cached_bucket_list = False

    def put_file(self, name: str, abspath: str, only_if_modified: bool = True) -> str:
        obj = self.s3.Object(self.bucket.name, name)

        if only_if_modified:
            if os.path.exists(abspath):
                size_on_s3 = self.file_size(name)
                if size_on_s3 > 0:
                    if os.path.getsize(abspath) == size_on_s3:
                        # File already exists and has the same size
                        print(
                            " *",
                            f"skipping putting {name} on S3 from {abspath}... (already there)",
                        )
                        return

        print(" *", f"putting {name} on S3 from {abspath}...")
        obj.upload_file(abspath)
        obj.Acl().put(ACL="public-read")

    def write_json(self, name: str, obj: Union[Dict, Sequence]) -> int:
        obj_data = json.dumps(obj, indent=2)
        obj = self.s3.Object(self.bucket.name, name)

        obj.put(Body=obj_data, ACL="public-read", ContentType="application/json")
        return obj.content_length

    def read_json(self, name: str) -> Union[Dict, Sequence]:
        obj = self.s3.Object(self.bucket.name, name)
        try:
            response = obj.get()
            return json.loads(response["Body"].read().decode("utf-8"))
        except self.s3.meta.client.exceptions.NoSuchKey:
            return None

    def rm_files(self, filenames):
        for filename in filenames:
            print(" *", "rm", filename)
            self.bucket.Object(filename).delete()

    def file_exists(self, filename):
        try:
            self.s3.Object(self.bucket.name, filename).load()
            return True
        except self.s3.meta.client.exceptions.NoSuchKey:
            return False

    def file_size(self, filename):
        try:
            obj = self.s3.Object(self.bucket.name, filename)
            return obj.content_length
        except self.s3.meta.client.exceptions.NoSuchKey:
            return -1

    def list_files(self):
        if not self.cached_bucket_list:
            self.cached_bucket_list = [
                (obj.key, obj.size) for obj in self.bucket.objects.all()
            ]

        return self.cached_bucket_list
