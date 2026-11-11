"""Only publish the static allowlist. Do not log credentials or bucket policy."""
import mimetypes
import os
from pathlib import Path
import sys

from qcloud_cos import CosConfig, CosS3Client

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.stage_site import PUBLIC_FILES, stage


def main():
    directory = Path('build/site')
    stage(Path.cwd(), directory)
    client = CosS3Client(CosConfig(Region=os.environ['COS_REGION'],
        SecretId=os.environ['TENCENTCLOUD_SECRET_ID'], SecretKey=os.environ['TENCENTCLOUD_SECRET_KEY'],
        Scheme='https'))
    for name in PUBLIC_FILES:
        client.put_object(Bucket=os.environ['COS_BUCKET'], Key=name,
            Body=(directory / name).read_bytes(),
            ContentType=(mimetypes.guess_type(name)[0] or 'application/octet-stream') + '; charset=utf-8',
            CacheControl='no-cache')
        print('Published ' + name)


if __name__ == '__main__':
    main()
