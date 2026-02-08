import boto3
import os
import time
import uuid
import mimetypes
import json
import urllib.request
import threading
import requests
import io
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
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

def deduplicate_tags(tags):
    """Remove duplicate tags (case-insensitive) while preserving original casing of first occurrence"""
    seen = set()
    unique = []
    for tag in tags:
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen.add(tag_lower)
            unique.append(tag)
    return unique

def process_transcription_job_background(job_name, bucket, file_key, db_item_key):
    """Background task: Poll transcription job and update DynamoDB when complete"""
    print(f"[BACKGROUND] Monitoring transcription job: {job_name}")
    try:
        max_attempts = 720  # 12 hours (polling every 60 seconds)
        attempt = 0
        
        while attempt < max_attempts:
            try:
                job_response = transcribe.get_transcription_job(
                    TranscriptionJobName=job_name
                )
                status = job_response['TranscriptionJob']['TranscriptionJobStatus']
                
                if attempt % 5 == 0:  # Log every 5 polls (5 minutes)
                    print(f"[BACKGROUND] Transcription status: {status} (elapsed: {attempt*60}s)")
                
                if status == 'COMPLETED':
                    print(f"[BACKGROUND] Transcription completed: {job_name}")
                    transcript_uri = job_response['TranscriptionJob']['Transcript']['TranscriptFileUri']
                    
                    try:
                        with urllib.request.urlopen(transcript_uri) as url_response:
                            transcript_json = json.loads(url_response.read().decode('utf-8'))
                            if 'results' in transcript_json and 'transcripts' in transcript_json['results']:
                                transcripts = transcript_json['results']['transcripts']
                                if len(transcripts) > 0:
                                    transcript_text = transcripts[0]['transcript']
                                    print(f"[BACKGROUND] Extracted transcript ({len(transcript_text)} chars)")
                                    
                                    # Generate tags from transcript using Comprehend
                                    transcript_tags = get_text_tags(transcript_text)
                                    transcript_tags = deduplicate_tags(transcript_tags)
                                    print(f"[BACKGROUND] Generated {len(transcript_tags)} unique tags from transcript")
                                    
                                    # Get visual labels if this is a video (they're stored separately)
                                    final_tags = transcript_tags
                                    visual_labels = []
                                    
                                    if dynamodb:
                                        # Retrieve current item to get visual labels
                                        item_response = dynamodb.get_item(Key={'filename': db_item_key})
                                        if 'Item' in item_response:
                                            visual_labels = item_response['Item'].get('visual_labels', [])
                                            print(f"[BACKGROUND] Found {len(visual_labels)} visual labels from video")
                                        
                                        # Combine transcript tags and visual labels (remove duplicates case-insensitively)
                                        combined = transcript_tags + visual_labels
                                        final_tags = deduplicate_tags(combined)[:15]
                                        print(f"[BACKGROUND] Combined tags: {len(final_tags)} unique total (transcript + visual)")
                                        
                                        # Update DynamoDB with both transcript and combined tags
                                        dynamodb.update_item(
                                            Key={'filename': db_item_key},
                                            UpdateExpression='SET tags = :tags, transcript = :transcript',
                                            ExpressionAttributeValues={
                                                ':tags': final_tags,
                                                ':transcript': transcript_text
                                            }
                                        )
                                        print(f"[BACKGROUND] Updated DynamoDB with transcript and {len(final_tags)} final tags")
                                    return
                    except Exception as e:
                        print(f"[BACKGROUND] Error processing transcript: {e}")
                        import traceback
                        traceback.print_exc()
                        return
                        
                elif status == 'FAILED':
                    print(f"[BACKGROUND] Transcription failed: {job_response['TranscriptionJob'].get('FailureReason', 'Unknown')}")
                    return
                
            except Exception as e:
                print(f"[BACKGROUND] Error polling job: {e}")
            
            attempt += 1
            time.sleep(60)  # Poll every 60 seconds
        
        print(f"[BACKGROUND] Transcription job timed out: {job_name}")
    except Exception as e:
        print(f"[BACKGROUND] Fatal error in transcription background task: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"[BACKGROUND] Fatal error in transcription background task: {e}")
        import traceback
        traceback.print_exc()

def process_video_job_background(job_id, db_item_key):
    """Background task: Poll video label detection job and update DynamoDB when complete"""
    print(f"[BACKGROUND] Monitoring video job: {job_id}")
    try:
        max_attempts = 600  # 10 hours (polling every 60 seconds)
        attempt = 0
        
        while attempt < max_attempts:
            try:
                job_response = rekognition.get_label_detection(JobId=job_id)
                status = job_response['JobStatus']
                
                if attempt % 5 == 0:  # Log every 5 polls (5 minutes)
                    print(f"[BACKGROUND] Video label detection status: {status} (elapsed: {attempt*60}s)")
                
                if status == 'SUCCEEDED':
                    print(f"[BACKGROUND] Video label detection completed: {job_id}")
                    labels_with_confidence = []
                    if 'Labels' in job_response:
                        for label_obj in job_response['Labels']:
                            if 'Label' in label_obj and 'Name' in label_obj['Label']:
                                confidence = label_obj.get('Label', {}).get('Confidence', 0)
                                # Only include labels with confidence >= 70
                                if confidence >= 70:
                                    labels_with_confidence.append({
                                        'name': label_obj['Label']['Name'],
                                        'confidence': confidence
                                    })
                    
                    # Sort by confidence (descending) and extract top 6 labels
                    sorted_labels = sorted(labels_with_confidence, key=lambda x: x['confidence'], reverse=True)
                    labels_list = [label['name'] for label in sorted_labels][:6]
                    labels_list = deduplicate_tags(labels_list)  # Ensure uniqueness
                    print(f"[BACKGROUND] Extracted {len(labels_list)} unique high-confidence visual labels from video")
                    
                    # Store visual labels in a temporary spot - will be merged with transcript tags later
                    if dynamodb:
                        dynamodb.update_item(
                            Key={'filename': db_item_key},
                            UpdateExpression='SET visual_labels = :labels',
                            ExpressionAttributeValues={':labels': labels_list}
                        )
                        print(f"[BACKGROUND] Stored visual labels for video")
                    return
                    
                elif status == 'FAILED':
                    print(f"[BACKGROUND] Video job failed: {job_response.get('StatusMessage', 'Unknown')}")
                    return
                    
            except Exception as e:
                print(f"[BACKGROUND] Error polling video job: {e}")
            
            attempt += 1
            time.sleep(60)  # Poll every 60 seconds
        
        print(f"[BACKGROUND] Video job timed out: {job_id}")
    except Exception as e:
        print(f"[BACKGROUND] Fatal error in video background task: {e}")
        import traceback
        traceback.print_exc()

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
    """Helper: Extract importance-weighted labels from image using AWS Rekognition"""
    if file_ext not in ['jpg', 'jpeg', 'png']:
        return [] 

    try:
        response = rekognition.detect_labels(
            Image={'S3Object': {'Bucket': bucket, 'Name': key}},
            MaxLabels=10,
            MinConfidence=70
        )
        
        # Filter by confidence (>= 0.75) and sort by confidence score
        high_confidence = [label for label in response['Labels'] if label.get('Confidence', 0) >= 99]
        sorted_labels = sorted(high_confidence, key=lambda x: x.get('Confidence', 0), reverse=True)
        
        # Extract names, limit to top 6
        return [label['Name'] for label in sorted_labels][:6]
    except Exception as e:
        print(f"AI Tagging Error: {e}")
        return []

def get_text_tags(text):
    """Extract importance-weighted tags from transcripts using Qwen 2.5-7B via Featherless API"""
    if not text or len(text.strip()) == 0:
        print("Warning: Empty text provided to get_text_tags")
        return []
    
    api_key = os.getenv("API_KEY")
    
    try:
        # Truncate to first 4000 chars to respect model limits
        text_truncated = text[:4000]
        
        prompt = f"""Analyze the following transcript and extract 5-8 of the MOST IMPORTANT and MEANINGFUL tags that capture the key topics, concepts, and ideas discussed. Focus on semantic importance and relevance, not just frequent words.

Transcript:
{text_truncated}

Respond with ONLY a comma-separated list of tags, nothing else. Example format: Machine Learning, Data Science, Neural Networks"""
        
        response = requests.post(
            "https://api.featherless.ai/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen-2.5-7b",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,  # Lower temperature for more focused output
                "max_tokens": 200
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                tags_text = result['choices'][0]['message']['content'].strip()
                # Parse comma-separated tags and clean them
                tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
                tags = deduplicate_tags(tags)[:8]
                print(f"Extracted {len(tags)} importance-weighted tags from transcript via Qwen")
                return tags
        else:
            print(f"Featherless API error: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        print(f"Text Tagging Error: {e}")
        return []

def process_text_file(bucket, key):
    """Download text file from S3 and extract tags using Qwen"""
    global s3_client
    if s3_client is None:
        startup()
    
    try:
        print(f"Processing text file {key}...")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        text_content = response['Body'].read().decode('utf-8', errors='ignore')
        print(f"Text file read: {len(text_content)} characters")
        tags = get_text_tags(text_content)
        print(f"Text file tags: {tags}")
        return tags
    except Exception as e:
        print(f"Text File Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def process_pdf_file(bucket, key):
    """Download PDF from S3, extract text, and send to Qwen for tags"""
    global s3_client
    if s3_client is None:
        startup()
    
    if PdfReader is None:
        print("PDF processing not available (pypdf not installed)")
        return []
    
    try:
        print(f"Processing PDF file {key}...")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_bytes = response['Body'].read()
        
        # Extract text from PDF
        try:
            pdf_reader = PdfReader(io.BytesIO(pdf_bytes))
            text_content = ""
            for page in pdf_reader.pages:
                text_content += page.extract_text() + " "
        except Exception as pdf_err:
            print(f"Error extracting text from PDF: {pdf_err}")
            return []
        
        if not text_content.strip():
            print("PDF contains no extractable text")
            return []
        
        print(f"PDF text extracted: {len(text_content)} characters")
        tags = get_text_tags(text_content)
        print(f"PDF tags: {tags}")
        return tags
    except Exception as e:
        print(f"PDF Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def process_audio_file(bucket, key, db_item_key):
    """Start AWS Transcribe job asynchronously and return immediately"""
    global transcribe, s3_client
    if transcribe is None:
        startup()
    
    try:
        print(f"Starting transcription for {key}...")
        # Start transcription job
        job_name = f"transcribe_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': f's3://{bucket}/{key}'},
            MediaFormat=key.split('.')[-1].lower(),
            LanguageCode='en-US'
        )
        print(f"Transcription job started: {job_name}")
        
        # Launch background thread to monitor job
        bg_thread = threading.Thread(
            target=process_transcription_job_background,
            args=(job_name, bucket, key, db_item_key),
            daemon=True
        )
        bg_thread.start()
        
        # Return immediately with empty tags (will be filled by background task)
        return []
    except Exception as e:
        print(f"Error starting transcription job: {e}")
        import traceback
        traceback.print_exc()
        return []

def process_video_file(bucket, key, db_item_key):
    """Start BOTH AWS Transcribe AND Rekognition Video jobs asynchronously"""
    global rekognition, transcribe
    if rekognition is None:
        startup()
    if transcribe is None:
        startup()
    
    try:
        print(f"Starting DUAL processing for video {key}...")
        
        # 1. Start Transcribe job for audio (with video file)
        print(f"  - Starting transcription for audio in {key}...")
        transcribe_job_name = f"transcribe_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        transcribe.start_transcription_job(
            TranscriptionJobName=transcribe_job_name,
            Media={'MediaFileUri': f's3://{bucket}/{key}'},
            MediaFormat=key.split('.')[-1].lower(),  # mp4, mov, etc.
            LanguageCode='en-US'
        )
        print(f"  ✓ Transcription job started: {transcribe_job_name}")
        
        # 2. Start Rekognition Video job for visual labels
        print(f"  - Starting visual label detection for {key}...")
        client_request_token = uuid.uuid4().hex[:8]
        start_response = rekognition.start_label_detection(
            Video={'S3Object': {'Bucket': bucket, 'Name': key}},
            ClientRequestToken=client_request_token,
            MinConfidence=70
        )
        video_job_id = start_response['JobId']
        print(f"  ✓ Video label detection job started: {video_job_id}")
        
        # 3. Launch background thread for transcription (will generate tags from transcript + merge with visual labels)
        bg_thread_transcribe = threading.Thread(
            target=process_transcription_job_background,
            args=(transcribe_job_name, bucket, key, db_item_key),
            daemon=True
        )
        bg_thread_transcribe.start()
        
        # 4. Launch background thread for video label detection
        bg_thread_video = threading.Thread(
            target=process_video_job_background,
            args=(video_job_id, db_item_key),
            daemon=True
        )
        bg_thread_video.start()
        
        print(f"✓ Both background tasks started for {key}")
        return []
    except Exception as e:
        print(f"Error starting video processing: {e}")
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
            print("Processing as TEXT using Qwen...")
            tags = process_text_file(AWS_BUCKET, key)
        elif file_ext in ['pdf']:
            print("Processing as PDF using Qwen...")
            tags = process_pdf_file(AWS_BUCKET, key)
        elif file_ext in ['mp3', 'wav']:
            print("Processing as AUDIO using Transcribe (background task)...")
            tags = process_audio_file(AWS_BUCKET, key, key)
        elif file_ext in ['mp4', 'mov']:
            print("Processing as VIDEO using Rekognition Video (background task)...")
            tags = process_video_file(AWS_BUCKET, key, key)
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
                        'transcript': '',  # Will be filled in by background task for audio/video
                        'visual_labels': [],  # Will be filled in by video job background task
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
            original_name = item.get('original_name', key)
            file_ext = original_name.split('.')[-1].lower()
            
            # Generate fresh URL
            fresh_url = s3_client.generate_presigned_url(
                'get_object', 
                Params={'Bucket': AWS_BUCKET, 'Key': key}, 
                ExpiresIn=3600
            )
            
            # Check if file is audio or video
            is_audio_or_video = file_ext in ['mp3', 'wav', 'aac', 'mp4', 'mov', 'avi', 'mkv']
            
            final_list.append({
                "name": original_name,
                "key": key,
                "url": fresh_url,
                "tags": item.get('tags', []),
                "transcript": item.get('transcript', ''),
                "is_audio_or_video": is_audio_or_video,
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

def get_transcript(key: str):
    """Retrieve transcript for a file from DynamoDB"""
    global dynamodb
    if dynamodb is None: startup()
    try:
        response = dynamodb.get_item(Key={'filename': key})
        if 'Item' in response:
            item = response['Item']
            transcript = item.get('transcript', '')
            file_name = item.get('original_name', key)
            return {
                'success': True,
                'filename': file_name,
                'transcript': transcript,
                'has_transcript': len(transcript) > 0
            }
        else:
            return {
                'success': False,
                'error': 'File not found'
            }
    except Exception as e:
        print(f"Get Transcript Error: {e}")
        return {
            'success': False,
            'error': str(e)
        }

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