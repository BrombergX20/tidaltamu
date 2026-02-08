import boto3
import os
import time
import uuid
from fastapi import HTTPException
from dotenv import load_dotenv

load_dotenv()

AWS_BUCKET = os.getenv('BUCKET_NAME') or os.getenv('S3_BUCKET') or os.getenv('tidaltamufiles')
S3_REGION = os.getenv('S3_REGION') or os.getenv('REGION')

if not AWS_BUCKET:
    raise RuntimeError('Environment variable BUCKET_NAME (or S3_BUCKET) must be set')

try:
    s3_client = boto3.client('s3', region_name=S3_REGION if S3_REGION else None)
    
except Exception as e:
    raise RuntimeError(f'Failed to create S3 client: {e}')

def make_key(filename: str) -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def upload_file(file_path: str) -> str:
    filename = file_path.split('/')[-1].lower().split('.')[0]
    extension = file_path.split('.')[-1].lower()
    key = make_key(filename)
    print("Got a file: ", filename, " with extension: ", extension)
    
    try:
        contents = open(file_path, 'rb').read()
        s3_client.put_object(Bucket=AWS_BUCKET, Key=key, Body=contents, ContentType=extension)
        url = s3_client.generate_presigned_url('get_object', Params={'Bucket': AWS_BUCKET, 'Key': key}, ExpiresIn=3600)
        return {'key': key, 'name': filename, 'url': url, 'content_type': extension}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')