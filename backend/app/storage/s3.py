import io, mimetypes
from contextlib import closing
from boto3.s3.transfer import TransferConfig
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
    def put_file(self, key, source, content_type="application/octet-stream"):
        source.seek(0)
        self.client.upload_fileobj(source,self.bucket,key,ExtraArgs={"ContentType":content_type},
            Config=TransferConfig(multipart_threshold=8*1024*1024,multipart_chunksize=8*1024*1024,max_concurrency=2))
        return key
    def open_read(self, key):
        return closing(self.client.get_object(Bucket=self.bucket, Key=key)["Body"])
    def get_bytes(self, key, progress=None):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        with closing(response["Body"]) as source:
            if progress is None: return source.read()
            output = io.BytesIO()
            while chunk := source.read(1024*1024):
                output.write(chunk)
                progress(output.tell(), response["ContentLength"])
            return output.getvalue()
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
