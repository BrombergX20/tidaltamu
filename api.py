import os
import time
import uuid
from typing import List

from dotenv import load_dotenv

import boto3
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI()

# Configure CORS origins via environment variable `ALLOWED_ORIGINS` (comma-separated).
allowed = os.getenv('https://testfiles.d2lyi075sbf5dh.amplifyapp.com')
if allowed:
    origins = [o.strip() for o in allowed.split(',') if o.strip()]
else:
    origins = ['https://testfiles.d2lyi075sbf5dh.amplifyapp.com''https://main.d2lyi075sbf5dh.amplifyapp.com/']

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

print(f"Configured S3 bucket: {AWS_BUCKET} in region: {S3_REGION or 'default'}")


@app.post('/upload')
async def upload_file(file: UploadFile = File(...)):
    """Receive a file and upload it to the configured S3 bucket. Returns a presigned GET URL."""
    key = make_key(file.filename)
    try:
        contents = await file.read()
        s3_client.put_object(Bucket=AWS_BUCKET, Key=key, Body=contents, ContentType=file.content_type)
        url = s3_client.generate_presigned_url('get_object', Params={'Bucket': AWS_BUCKET, 'Key': key}, ExpiresIn=3600)
        return {'key': key, 'name': file.filename, 'url': url, 'content_type': file.content_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')


@app.get('/files')
def list_files() -> List[dict]:
    """List objects in the S3 bucket and return metadata with presigned URLs."""
    try:
        resp = s3_client.list_objects_v2(Bucket=AWS_BUCKET)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to list bucket: {e}')

    items = []
    for obj in resp.get('Contents', []):
        key = obj['Key']
        try:
            url = s3_client.generate_presigned_url('get_object', Params={'Bucket': AWS_BUCKET, 'Key': key}, ExpiresIn=3600)
        except Exception:
            url = ''
        # Derive a friendly name from the original filename appended after the generated prefix
        parts = key.split('_')
        name = parts[-1] if len(parts) >= 1 else key
        items.append({'key': key, 'name': name, 'url': url, 'size': obj['Size'], 'last_modified': obj['LastModified'].isoformat()})

    return items


if __name__ == '__main__':
    print('FastAPI S3 backend module. Run with: uvicorn api:app --reload')