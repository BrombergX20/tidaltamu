import boto3
import os
import time
import uuid
import mimetypes
from fastapi import HTTPException
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# Global variables
s3_client = None
AWS_BUCKET = None

def make_key(filename: str) -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def startup():
    global s3_client, AWS_BUCKET
    
    # 1. Get Settings
    AWS_REGION = os.getenv("S3_REGION")
    AWS_BUCKET = os.getenv("BUCKET_NAME")

    if not AWS_BUCKET:
        print("CRITICAL ERROR: AWS_BUCKET not found. Check .env file.")

    # 2. Connect to S3 (Using EC2 Role - No manual keys!)
    if s3_client is None:
        try:
            s3_client = boto3.client('s3', region_name=AWS_REGION)
            print(f"S3 Connection Initialized. Bucket: {AWS_BUCKET}")
        except Exception as e:
            print(f"Failed to connect to S3: {e}")

def upload_file(file_path: str) -> str:
    global s3_client, AWS_BUCKET
    if s3_client is None: startup()
        
    file_name = file_path.split('/')[-1]
    key = make_key(file_name)
    
    try:
        # FIX 1: Open in Binary Mode ("rb") prevents PDF crashes
        with open(file_path, "rb") as f:
            contents = f.read()

        # determine a proper MIME content type for the object
        content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        s3_client.put_object(
            Bucket=AWS_BUCKET,
            Key=key,
            Body=contents,
            ContentType=content_type
        )
        
        url = s3_client.generate_presigned_url(
            'get_object', 
            Params={'Bucket': AWS_BUCKET, 'Key': key}, 
            ExpiresIn=3600
        )
        
        return {'key': key, 'name': file_name, 'url': url, 'content_type': content_type}

    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')

# FIX 3: Renamed from get_files to list_files to match api.py
def list_files():
    global s3_client, AWS_BUCKET
    if s3_client is None: startup()

    try:
        response = s3_client.list_objects_v2(Bucket=AWS_BUCKET)
        files = []
        
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                url = s3_client.generate_presigned_url(
                    'get_object', 
                    Params={'Bucket': AWS_BUCKET, 'Key': key}, 
                    ExpiresIn=3600
                )
                
                try:
                    display_name = key.split('_', 2)[-1]
                except:
                    display_name = key

                files.append({
                    "name": display_name,
                    "url": url,
                    "size": obj['Size']
                })
        return files
    except Exception as e:
        print(f"LIST ERROR: {e}")
        return []