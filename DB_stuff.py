import boto3
import os
import time
import uuid
from fastapi import HTTPException
from dotenv import load_dotenv

# Load variables from the .env file immediately
load_dotenv()

# Global variables
s3_client = None
AWS_BUCKET = None

def make_key(filename: str) -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def startup():
    global s3_client, AWS_BUCKET
    
    # 1. Get values from .env
    AWS_REGION = os.getenv("S3_REGION")
    AWS_BUCKET = os.getenv("BUCKET_NAME")
    
    # Safety Check: detailed error if .env is missing
    if not AWS_BUCKET:
        print("CRITICAL ERROR: 'AWS_BUCKET' is missing. Did you create the .env file?")
    if not AWS_REGION:
        print("WARNING: 'AWS_REGION' is missing. Defaulting to us-east-1.")
        AWS_REGION = "us-east-1"

    # 2. Connect to S3 (Using EC2 IAM Role + Region from env)
    if s3_client is None:
        s3_client = boto3.client('s3', region_name=AWS_REGION)
        print(f"S3 Initialized. Target Bucket: {AWS_BUCKET}")

def upload_file(file_path: str) -> str:
    global s3_client, AWS_BUCKET
    
    # Ensure startup ran
    if s3_client is None or AWS_BUCKET is None:
        startup()
        
    file_name = file_path.split('/')[-1]
    key = make_key(file_name)
    
    try:
        # Open in Binary Mode ("rb") for PDF/Images
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
    

def list_files():
    startup() # Ensure connected
    try:
        response = s3_client.list_objects_v2(Bucket=AWS_BUCKET)
        
        files = []
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                # Generate a temporary link (valid for 1 hour)
                url = s3_client.generate_presigned_url(
                    'get_object', 
                    Params={'Bucket': AWS_BUCKET, 'Key': key}, 
                    ExpiresIn=3600
                )
                
                # Try to clean up the name (remove the timestamp/UUID prefix)
                # Key format is: time_uuid_filename
                try:
                    clean_name = key.split('_', 2)[-1]
                except:
                    clean_name = key

                files.append({
                    "key": key,
                    "name": clean_name,
                    "url": url,
                    "size": obj['Size']
                })
        return files
        
    except Exception as e:
        print(f"LIST ERROR: {str(e)}")
        return []