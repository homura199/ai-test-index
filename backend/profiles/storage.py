"""Private COS persistence; the website bucket must never be used for profiles."""
import json
import re


class CosStore:
    def __init__(self, client_factory, bucket):
        self.client_factory = client_factory
        self.bucket = bucket

    @staticmethod
    def key(kind, identifier):
        if kind not in ("profiles", "tickets", "submissions") or not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("Invalid object key")
        return f"lesson-one/{kind}/{identifier}.json"

    def get(self, kind, identifier):
        from qcloud_cos.cos_exception import CosServiceError
        try:
            obj = self.client_factory().get_object(Bucket=self.bucket, Key=self.key(kind, identifier))
            return json.loads(obj["Body"].get_raw_stream().read(128 * 1024))
        except CosServiceError as exc:
            if exc.get_status_code() == 404:
                return None
            raise

    def put(self, kind, identifier, value):
        self.client_factory().put_object(
            Bucket=self.bucket, Key=self.key(kind, identifier),
            Body=json.dumps(value, ensure_ascii=False).encode(), ContentType="application/json",
            ServerSideEncryption="AES256",
        )

    def create(self, kind, identifier, value):
        """Atomically create a public submission without overwriting prior work."""
        from qcloud_cos.cos_exception import CosServiceError
        client = self.client_factory()
        # COS forbid-overwrite is ineffective in versioned buckets. Fail closed.
        versioning = client.get_bucket_versioning(Bucket=self.bucket)
        if versioning.get('Status'):
            raise RuntimeError('Student submission requires an unversioned private bucket')
        try:
            client.put_object(Bucket=self.bucket, Key=self.key(kind, identifier),
                Body=json.dumps(value, ensure_ascii=False).encode(), ContentType='application/json',
                ServerSideEncryption='AES256', ForbidOverwrite='true')
            return True
        except CosServiceError as exc:
            if exc.get_status_code() == 409:
                return False
            raise


def production_store(bucket, region):
    import os
    from qcloud_cos import CosConfig, CosS3Client

    def factory():
        # Fetch SCF execution-role credentials on each operation; do not persist a
        # warmed instance's expired temporary credentials in a module-level client.
        secret_id = os.environ.get("TENCENTCLOUD_SECRETID")
        secret_key = os.environ.get("TENCENTCLOUD_SECRETKEY")
        token = os.environ.get("TENCENTCLOUD_SESSIONTOKEN")
        if not all((secret_id, secret_key, token)):
            raise RuntimeError("SCF execution role is required for private COS access")
        return CosS3Client(CosConfig(Region=region, SecretId=secret_id,
                                    SecretKey=secret_key, Token=token, Scheme="https"))

    return CosStore(factory, bucket)
