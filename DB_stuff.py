import boto3
import os
import time
import uuid
from fastapi import HTTPException
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# Global variables
s3_client = None
AWS_BUCKET = None

def make_key(filename: str) -> str:
    # Creates unique filename: 1709923_randomuuid_myFile.pdf
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def startup():
    global s3_client, AWS_BUCKET
    
    # 1. Get Settings
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_BUCKET = os.getenv("AWS_BUCKET")

    if not AWS_BUCKET:
        print("CRITICAL ERROR: AWS_BUCKET not found in .env")

    # 2. Connect to S3 (Using EC2 Role)
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
        # Open in Binary Mode ('rb') to fix PDF/Image errors
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
        
        return {'key': key, 'name': file_name, 'url': url}

    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')

def list_files():
    # NEW FUNCTION: Gets list of all files in bucket
    global s3_client, AWS_BUCKET
    if s3_client is None: startup()

    try:
        response = s3_client.list_objects_v2(Bucket=AWS_BUCKET)
        files = []
        
        if 'Contents' in response:
            for obj in response['Contents']:
                key = obj['Key']
                # Generate View Link
                url = s3_client.generate_presigned_url(
                    'get_object', 
                    Params={'Bucket': AWS_BUCKET, 'Key': key}, 
                    ExpiresIn=3600
                )
                
                # Clean up name (remove timestamp prefix)
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