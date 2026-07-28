import io, mimetypes
import boto3
from botocore.client import Config
from app.core.config import settings

class ObjectStore:
    def __init__(self):
        self.client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4"), region_name="us-east-1")
        self.bucket = settings.s3_bucket
        self.ensure_bucket()
    def ensure_bucket(self):
        buckets = [b["Name"] for b in self.client.list_buckets().get("Buckets", [])]
        if self.bucket not in buckets:
            self.client.create_bucket(Bucket=self.bucket)
    def put_bytes(self, key, data: bytes, content_type=None):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type or mimetypes.guess_type(key)[0] or "application/octet-stream")
        return key
    def get_bytes(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
    def delete_key(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)
    def delete_prefix(self, prefix):
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
    def presigned_url(self, key, expires=3600):
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires)

store = ObjectStore
