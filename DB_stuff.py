import boto3
import os
import time
import uuid
from fastapi import HTTPException
from dotenv import load_dotenv
from boto3.dynamodb.conditions import Attr

load_dotenv()

# Global variables
s3_client = None
rekognition = None
dynamodb = None
AWS_BUCKET = None

def make_key(filename: str) -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def startup():
    global s3_client, AWS_BUCKET, rekognition, dynamodb
    
    AWS_REGION = os.getenv("S3_REGION", "us-east-1")
    AWS_BUCKET = os.getenv("BUCKET_NAME")

    if not AWS_BUCKET:
        print("CRITICAL ERROR: AWS_BUCKET not found. Check .env file.")

    if s3_client is None:
        try:
            # 1. Connect to S3
            s3_client = boto3.client('s3', region_name=AWS_REGION)
            
            # 2. Connect to Rekognition (AI)
            rekognition = boto3.client('rekognition', region_name=AWS_REGION)
            
            # 3. Connect to DynamoDB (Database)
            dynamo_resource = boto3.resource('dynamodb', region_name=AWS_REGION)
            dynamodb = dynamo_resource.Table('MediaTags')
            
            print(f"AWS Services Initialized. Bucket: {AWS_BUCKET}")
        except Exception as e:
            print(f"Failed to connect to AWS: {e}")

def get_ai_tags(bucket, key, file_ext):
    """Helper: Asks AWS Rekognition what is in the image"""
    if file_ext not in ['jpg', 'jpeg', 'png']:
        return [] 

    try:
        response = rekognition.detect_labels(
            Image={'S3Object': {'Bucket': bucket, 'Name': key}},
            MaxLabels=5,
            MinConfidence=80
        )
        return [label['Name'] for label in response['Labels']]
    except Exception as e:
        print(f"AI Tagging Error: {e}")
        return []

def upload_file(file_path: str) -> str:
    global s3_client, AWS_BUCKET, dynamodb
    if s3_client is None: startup()
        
    file_name = file_path.split('/')[-1]
    key = make_key(file_name)
    file_ext = file_name.split('.')[-1].lower()
    
    try:
        # 1. Upload to S3 (Binary Mode)
        with open(file_path, "rb") as f:
            contents = f.read()

        s3_client.put_object(
            Bucket=AWS_BUCKET, 
            Key=key, 
            Body=contents, 
            ContentType=file_ext
        )
        
        url = s3_client.generate_presigned_url(
            'get_object', 
            Params={'Bucket': AWS_BUCKET, 'Key': key}, 
            ExpiresIn=3600
        )
        
        # 2. Ask AI for Tags
        tags = get_ai_tags(AWS_BUCKET, key, file_ext)
        
        # 3. Save to DynamoDB
        if dynamodb:
            try:
                dynamodb.put_item(
                    Item={
                        'filename': key,
                        'original_name': file_name,
                        'url': url,
                        'tags': tags,
                        'created_at': str(int(time.time()))
                    }
                )
            except Exception as e:
                print(f"DB Save Error: {e}")

        return {'key': key, 'name': file_name, 'url': url, 'tags': tags}

    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')

def list_files():
    # Lists files from S3
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
                try: display_name = key.split('_', 2)[-1]
                except: display_name = key

                files.append({
                    "key": key,
                    "name": display_name,
                    "url": url,
                    "size": obj['Size']
                })
        return files
    except Exception as e:
        print(f"LIST ERROR: {e}")
        return []

def search_files(query: str):
    # Searches DynamoDB
    global dynamodb
    if dynamodb is None: startup()
    
    try:
        response = dynamodb.scan(
            FilterExpression=Attr('tags').contains(query) | Attr('original_name').contains(query)
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"Search Error: {e}")
        return []
def delete_file(key: str) -> bool:
    """Delete object from S3 by key. Returns True on success."""
    global s3_client, AWS_BUCKET
    if s3_client is None: startup()
    try:
        s3_client.delete_object(Bucket=AWS_BUCKET, Key=key)
        return True
    except Exception as e:
        print(f"DELETE ERROR: {e}")
        return False