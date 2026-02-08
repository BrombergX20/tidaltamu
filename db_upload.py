import boto3
import os
import time
import uuid
from fastapi import HTTPException
from dotenv import load_dotenv

load_dotenv()

# Global variables
s3_client = None
AWS_BUCKET = None

def make_key(filename: str) -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def startup():
    global s3_client, AWS_BUCKET
    AWS_REGION = os.getenv("S3_REGION")
    AWS_BUCKET = os.getenv("BUCKET_NAME") # <--- MAKE SURE THIS IS SET
    
    if s3_client is None:
        s3_client = boto3.client('s3', region_name=AWS_REGION)
        print("S3 Client Initialized")

def upload_file(file_path: str) -> str:
    # CRITICAL FIX: Check if s3_client exists, if not, start it up.
    global s3_client, AWS_BUCKET
    if s3_client is None:
        startup()
        
    file_name = file_path.split('/')[-1]
    key = make_key(file_name)
    
    try:
        # Open in Binary Mode
        with open(file_path, "rb") as f:
            contents = f.read()

        s3_client.put_object(
            Bucket=AWS_BUCKET, 
            Key=key, 
            Body=contents, 
            ContentType=file_name.split('.')[-1]
        )
        
        url = s3_client.generate_presigned_url(
            'get_object', 
            Params={'Bucket': AWS_BUCKET, 'Key': key}, 
            ExpiresIn=3600
        )
        
        return {'key': key, 'name': file_name, 'url': url, 'content_type': file_name.split('.')[-1]}

    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')