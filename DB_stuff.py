import boto3
import os
import time
import uuid
import mimetypes
import json
import urllib.request
from fastapi import HTTPException
from dotenv import load_dotenv
from boto3.dynamodb.conditions import Attr

load_dotenv()

# Global variables
s3_client = None
rekognition = None
comprehend = None
transcribe = None
dynamodb = None
AWS_BUCKET = None

def make_key(filename: str) -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"

def startup():
    global s3_client, AWS_BUCKET, rekognition, comprehend, transcribe, dynamodb
    
    AWS_REGION = os.getenv("S3_REGION")
    AWS_BUCKET = os.getenv("BUCKET_NAME")

    if not AWS_BUCKET:
        print("CRITICAL ERROR: AWS_BUCKET not found. Check .env file.")

    if s3_client is None:
        try:
            s3_client = boto3.client('s3', region_name=AWS_REGION)
            rekognition = boto3.client('rekognition', region_name=AWS_REGION)
            comprehend = boto3.client('comprehend', region_name=AWS_REGION)
            transcribe = boto3.client('transcribe', region_name=AWS_REGION)
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

def get_text_tags(text):
    """Extract tags from text using AWS Comprehend key phrases"""
    global comprehend
    if comprehend is None:
        startup()
    
    if not text or len(text.strip()) == 0:
        print("Warning: Empty text provided to get_text_tags")
        return []
    
    try:
        response = comprehend.detect_key_phrases(
            Text=text[:5000],  # Comprehend has 5000 char limit per request
            LanguageCode='en'
        )
        tags = [phrase['Text'] for phrase in response.get('KeyPhrases', [])]
        print(f"Extracted {len(tags)} tags from text via Comprehend")
        return tags[:10]  # Limit to 10 top tags
    except Exception as e:
        print(f"Text Tagging Error: {e}")
        return []

def process_text_file(bucket, key):
    """Download text file from S3 and extract tags using Comprehend"""
    global s3_client
    if s3_client is None:
        startup()
    
    try:
        print(f"Processing text file {key}...")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        text_content = response['Body'].read().decode('utf-8')
        print(f"Text file read: {len(text_content)} characters")
        tags = get_text_tags(text_content)
        print(f"Text file tags: {tags}")
        return tags
    except Exception as e:
        print(f"Text File Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def process_audio_file(bucket, key):
    """Start AWS Transcribe job, wait for completion, and extract tags"""
    global transcribe, s3_client
    if transcribe is None:
        startup()
    
    try:
        print(f"Starting transcription for {key}...")
        # Start transcription job
        job_name = f"transcribe_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'S3Object': {'Bucket': bucket, 'Key': key}},
            MediaFormat=key.split('.')[-1].lower(),  # mp3, wav, etc.
            LanguageCode='en-US'
        )
        
        # Wait for job to complete
        max_attempts = 60
        attempt = 0
        while attempt < max_attempts:
            job_response = transcribe.get_transcription_job(
                TranscriptionJobName=job_name
            )
            status = job_response['TranscriptionJob']['TranscriptionJobStatus']
            print(f"Transcription status: {status} (attempt {attempt+1}/{max_attempts})")
            
            if status == 'COMPLETED':
                print(f"Transcription completed for {key}")
                # Download the transcript JSON
                transcript_uri = job_response['TranscriptionJob']['Transcript']['TranscriptFileUri']
                try:
                    with urllib.request.urlopen(transcript_uri) as url_response:
                        transcript_json = json.loads(url_response.read().decode('utf-8'))
                        if 'results' in transcript_json and 'transcripts' in transcript_json['results']:
                            transcripts = transcript_json['results']['transcripts']
                            if len(transcripts) > 0:
                                transcript_text = transcripts[0]['transcript']
                                print(f"Extracted transcript: {transcript_text[:100]}...")
                                tags = get_text_tags(transcript_text)
                                return tags
                        else:
                            print("No transcripts found in response")
                            return []
                except Exception as url_err:
                    print(f"Error downloading transcript from {transcript_uri}: {url_err}")
                    return []
            elif status == 'FAILED':
                failure_reason = job_response['TranscriptionJob'].get('FailureReason', 'Unknown error')
                print(f"Transcription job failed: {failure_reason}")
                return []
            
            attempt += 1
            time.sleep(1)
        
        print("Transcription job timed out")
        return []
    except Exception as e:
        print(f"Audio File Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def process_video_file(bucket, key):
    """Start AWS Rekognition Video job, wait for completion, and extract labels"""
    global rekognition
    if rekognition is None:
        startup()
    
    try:
        print(f"Starting video label detection for {key}...")
        # Start label detection job for video
        client_request_token = uuid.uuid4().hex[:8]
        start_response = rekognition.start_label_detection(
            Video={'S3Object': {'Bucket': bucket, 'Name': key}},
            ClientRequestToken=client_request_token,
            MinConfidence=70
        )
        
        job_id = start_response['JobId']
        print(f"Video label detection job started: {job_id}")
        
        # Wait for job to complete
        max_attempts = 300  # 5 minutes with 1 second intervals
        attempt = 0
        while attempt < max_attempts:
            job_response = rekognition.get_label_detection(
                JobId=job_id
            )
            status = job_response['JobStatus']
            
            if attempt % 10 == 0:  # Log every 10 attempts
                print(f"Video label detection status: {status} (attempt {attempt+1}/{max_attempts})")
            
            if status == 'SUCCEEDED':
                print(f"Video label detection completed for {key}")
                # Extract labels from all frames and get unique ones
                labels_set = set()
                if 'Labels' in job_response:
                    for label_obj in job_response['Labels']:
                        if 'Label' in label_obj and 'Name' in label_obj['Label']:
                            labels_set.add(label_obj['Label']['Name'])
                    print(f"Extracted {len(labels_set)} unique labels from video")
                else:
                    print("No Labels field in video response")
                
                return list(labels_set)[:10]  # Limit to 10 unique labels
            elif status == 'FAILED':
                failure_msg = job_response.get('StatusMessage', 'Unknown error')
                print(f"Video label detection failed: {failure_msg}")
                return []
            
            attempt += 1
            time.sleep(1)
        
        print("Video label detection job timed out")
        return []
    except Exception as e:
        print(f"Video File Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def upload_file(file_path: str) -> str:
    global s3_client, AWS_BUCKET, dynamodb
    if s3_client is None: startup()
        
    file_name = file_path.split('/')[-1]
    key = make_key(file_name)
    file_ext = file_name.split('.')[-1].lower()
    
    print(f"\n===== UPLOAD START: {file_name} (ext: {file_ext}) =====")
    
    try:
        # 1. Upload to S3
        with open(file_path, "rb") as f:
            contents = f.read()

        # Use proper MIME type for ContentType
        content_type, _ = mimetypes.guess_type(file_name)
        if not content_type:
            content_type = 'application/octet-stream'

        print(f"Uploading to S3: {key}")
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
        print(f"S3 upload complete. URL: {url[:50]}...")
        
        # 2. Get Tags based on file type & Save to DB
        tags = []
        
        if file_ext in ['jpg', 'jpeg', 'png']:
            print("Processing as IMAGE using Rekognition...")
            tags = get_ai_tags(AWS_BUCKET, key, file_ext)
        elif file_ext in ['txt', 'md']:
            print("Processing as TEXT using Comprehend...")
            tags = process_text_file(AWS_BUCKET, key)
        elif file_ext in ['mp3', 'wav']:
            print("Processing as AUDIO using Transcribe...")
            tags = process_audio_file(AWS_BUCKET, key)
        elif file_ext in ['mp4', 'mov']:
            print("Processing as VIDEO using Rekognition Video...")
            tags = process_video_file(AWS_BUCKET, key)
        else:
            print(f"Unsupported file type: {file_ext}")
        
        print(f"Final tags extracted: {tags}")
        
        if dynamodb:
            try:
                print(f"Saving to DynamoDB with tags: {tags}")
                dynamodb.put_item(
                    Item={
                        'filename': key,
                        'original_name': file_name,
                        'url': url,
                        'tags': tags,
                        'created_at': str(int(time.time()))
                    }
                )
                print("DynamoDB save successful")
            except Exception as e:
                print(f"DB Save Error: {e}")
                import traceback
                traceback.print_exc()

        print(f"===== UPLOAD COMPLETE: {file_name} =====\n")
        return {'key': key, 'name': file_name, 'url': url, 'tags': tags}

    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f'Upload failed: {e}')

def list_files():
    # Fetch from DynamoDB to get tags, but include 'key' for deletion
    global dynamodb, s3_client, AWS_BUCKET
    if dynamodb is None: startup()
    
    try:
        response = dynamodb.scan()
        items = response.get('Items', [])
        
        final_list = []
        for item in items:
            key = item['filename']
            # Generate fresh URL
            fresh_url = s3_client.generate_presigned_url(
                'get_object', 
                Params={'Bucket': AWS_BUCKET, 'Key': key}, 
                ExpiresIn=3600
            )
            
            final_list.append({
                "name": item.get('original_name', key),
                "key": key,  # <--- CRITICAL FOR DELETE BUTTON
                "url": fresh_url,
                "tags": item.get('tags', []),
                "size": 0 
            })
            
        return final_list
        
    except Exception as e:
        print(f"DB LIST ERROR: {e}")
        return []

def search_files(query: str):
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

def delete_file(key: str):
    # Helper to delete from S3 and DynamoDB
    global s3_client, AWS_BUCKET, dynamodb
    if s3_client is None: startup()
    
    try:
        # Delete from S3
        s3_client.delete_object(Bucket=AWS_BUCKET, Key=key)
        # Delete from DynamoDB
        if dynamodb:
            dynamodb.delete_item(Key={'filename': key})
        return True
    except Exception as e:
        print(f"Delete Error: {e}")
        return False