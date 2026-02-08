import boto3
import os
import time
import uuid
import uuid
import mimetypes
import json
import urllib.request
import threading
import requests
import time
import io
import base64
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
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
                                    
                                    # Get visual labels if this is a video (they're stored separately)
                                    final_tags = []
                                    visual_labels = []
                                    
                                    if dynamodb:
                                        # Retrieve current item to get visual labels
                                        item_response = dynamodb.get_item(Key={'filename': db_item_key})
                                        if 'Item' in item_response:
                                            visual_labels = item_response['Item'].get('visual_labels', [])
                                            print(f"[BACKGROUND] Found {len(visual_labels)} visual labels from video")
                                        
                                        # Check if transcript has meaningful content
                                        if transcript_text.strip() and len(transcript_text.strip()) >= 20:
                                            # Transcript is valid - generate tags from it
                                            transcript_tags = get_text_tags(transcript_text)
                                            transcript_tags = deduplicate_tags(transcript_tags)
                                            print(f"[BACKGROUND] Generated {len(transcript_tags)} unique tags from transcript")
                                            
                                            # Combine transcript tags and visual labels (remove duplicates case-insensitively)
                                            combined = transcript_tags + visual_labels
                                            final_tags = deduplicate_tags(combined)[:15]
                                            print(f"[BACKGROUND] Combined tags: {len(final_tags)} unique total (transcript + visual)")
                                        else:
                                            # Transcript is empty or too short - use only visual labels
                                            if visual_labels:
                                                final_tags = visual_labels[:15]
                                                print(f"[BACKGROUND] Transcript too short/empty, using {len(final_tags)} visual labels only")
                                            else:
                                                final_tags = []
                                                print(f"[BACKGROUND] No transcript and no visual labels available")
                                        
                                        # Update DynamoDB with both transcript and final tags
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
    global s3_client, AWS_BUCKET, rekognition, comprehend, transcribe, dynamodb, textract
    
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
            textract = boto3.client('textract', region_name=AWS_REGION) # Added Textract client
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
    """Extract importance-weighted tags from text using Amazon Comprehend."""
    global comprehend
    if comprehend is None:
        startup()

    if not text or len(text.strip()) == 0:
        print("Warning: Empty text provided to get_text_tags")
        return []
    
    try:
        # Comprehend can process up to 5000 characters per call for key phrases
        text_truncated = text[:4900] # Keep some buffer
        
        response = comprehend.detect_key_phrases(
            Text=text_truncated,
            LanguageCode='en'
        )
        
        tags = [phrase['Text'] for phrase in response['KeyPhrases'] if phrase['Score'] >= 0.8]
        tags = deduplicate_tags(tags)[:8] # Limit to top 8 unique tags
        
        print(f"Extracted {len(tags)} tags using Amazon Comprehend.")
        return tags
            
    except Exception as e:
        print(f"Comprehend Tagging Error: {e}")
        return []

def get_text_from_document_aws(document_bytes: bytes, file_type: str) -> str:
    """Extract text from a document (image or PDF) using Amazon Textract."""
    global textract, s3_client, AWS_BUCKET # Added s3_client and AWS_BUCKET
    if textract is None:
        startup()

    try:
        print(f"Textract: Attempting to detect text for file type: {file_type}")
        extracted_text = ""

        if file_type in ['png', 'jpeg']:
            response = textract.detect_document_text(
                Document={'Bytes': document_bytes}
            )
            for item in response["Blocks"]:
                if item["BlockType"] == "LINE":
                    extracted_text += item["Text"] + "\n"
        elif file_type == 'pdf':
            # For multi-page PDFs, use asynchronous Textract
            print("Textract: Starting asynchronous text detection for PDF.")

            # Generate a temporary S3 key for the PDF bytes
            temp_key = f"temp_textract_pdf/{uuid.uuid4().hex}.pdf"
            
            # Upload the PDF bytes to S3
            s3_client.put_object(Bucket=AWS_BUCKET, Key=temp_key, Body=document_bytes)
            print(f"Textract: Uploaded PDF to temporary S3 location: s3://{AWS_BUCKET}/{temp_key}")

            start_response = textract.start_document_text_detection(
                DocumentLocation={'S3Object': {'Bucket': AWS_BUCKET, 'Name': temp_key}}
            )
            job_id = start_response['JobId']
            print(f"Textract: Job started with ID: {job_id}")

            # Poll for job completion
            status = ''
            while status != 'SUCCEEDED' and status != 'FAILED':
                time.sleep(5) # Poll every 5 seconds
                job_response = textract.get_document_text_detection(JobId=job_id)
                status = job_response['JobStatus']
                print(f"Textract: Job status: {status}")

            # Delete the temporary S3 object after processing
            s3_client.delete_object(Bucket=AWS_BUCKET, Key=temp_key)
            print(f"Textract: Deleted temporary S3 object: s3://{AWS_BUCKET}/{temp_key}")

            if status == 'SUCCEEDED':
                pages = []
                next_token = None
                while True:
                    if next_token:
                        page_response = textract.get_document_text_detection(JobId=job_id, NextToken=next_token)
                    else:
                        page_response = job_response # First page is already in job_response

                    for item in page_response["Blocks"]:
                        if item["BlockType"] == "LINE":
                            extracted_text += item["Text"] + "\n"
                    
                    next_token = page_response.get('NextToken')
                    if not next_token:
                        break
            else:
                print(f"Textract: Asynchronous text detection failed for job ID: {job_id}")
                return ""
        else:
            print(f"Textract: Unsupported file type for Textract: {file_type}")
            return ""

        print(f"Textract: Extracted {len(extracted_text)} characters using Amazon Textract.")
        if not extracted_text.strip():
            print("Textract: Extracted text is empty or only whitespace.")
        return extracted_text
    except Exception as e:
        print(f"Textract: Error in get_text_from_document_aws: {e}")
        return ""

def process_text_file(bucket, key):
    """Download text file from S3 and extract tags using Qwen, return both tags and transcript"""
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
        return {'tags': tags, 'transcript': text_content}
    except Exception as e:
        print(f"Text File Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return {'tags': [], 'transcript': ''}

def process_pdf_file(bucket, key):
    """Download PDF from S3, extract text, and generate tags."""
    global s3_client
    if s3_client is None:
        startup()

    try:
        print(f"Processing PDF file {key}...")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_bytes = response['Body'].read()

        # 1) Try to extract text directly using pypdf
        extracted_text = ''
        if PdfReader is not None:
            try:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    try:
                        txt = page.extract_text() or ''
                        extracted_text += txt + '\n'
                    except Exception:
                        continue
                print(f"Successfully extracted {len(extracted_text)} characters using pypdf.")
            except Exception as e:
                print(f"pypdf extraction failed: {e}")

        # If text is extracted, generate tags and return with transcript
        if extracted_text and len(extracted_text.strip()) >= 50:
            print("Generating tags from pypdf extracted text.")
            tags = get_text_tags(extracted_text)
            return {'tags': tags, 'transcript': extracted_text}

        # 2) Fallback: If pypdf fails, use Amazon Textract for OCR
        print("pypdf failed or extracted too little text. Falling back to Amazon Textract for OCR.")
        ocr_text = get_text_from_document_aws(pdf_bytes, 'pdf')
        
        if ocr_text and len(ocr_text.strip()) >= 20:
            print(f"Successfully extracted {len(ocr_text)} characters using Amazon Textract fallback.")
            print("Generating tags from OCR extracted text.")
            tags = get_text_tags(ocr_text)
            return {'tags': tags, 'transcript': ocr_text}
        else:
            print("Amazon Textract fallback did not yield significant text.")

        print("Could not extract text from PDF using any method.")
        return {'tags': [], 'transcript': ''}
    except Exception as e:
        print(f"PDF Processing Error: {e}")
        import traceback
        traceback.print_exc()
        return {'tags': [], 'transcript': ''}

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
        transcript = ''
        
        if file_ext in ['jpg', 'jpeg', 'png']:
            print("Processing as IMAGE using Rekognition...")
            tags = get_ai_tags(AWS_BUCKET, key, file_ext)
        elif file_ext in ['txt', 'md', 'csv', 'json', 'xml', 'html', 'htm', 'log']:
            print("Processing as TEXT using Qwen...")
            result = process_text_file(AWS_BUCKET, key)
            tags = result['tags']
            transcript = result['transcript']
        elif file_ext in ['pdf']:
            print("Processing as PDF using Qwen...")
            result = process_pdf_file(AWS_BUCKET, key)
            tags = result['tags']
            transcript = result['transcript']
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
                        'transcript': transcript,  # Filled for .txt/.pdf; filled by background task for audio/video
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

def qwen_search_files(user_query: str):
    """Use Qwen to find files matching natural language query with three-pass approach: strict, lenient, then topic-based"""
    global dynamodb, s3_client, AWS_BUCKET
    if dynamodb is None: startup()
    
    api_key = os.getenv("API_KEY")
    
    try:
        print(f"[QWEN SEARCH] Fetching all files for context...")
        
        # Scan all files from DynamoDB
        response = dynamodb.scan()
        items = response.get('Items', [])
        
        if not items:
            print("[QWEN SEARCH] No files in database")
            return []
        
        # Build file context with transcripts and tags, numbered for easy reference
        file_context = []
        numbered_context = []
        for idx, item in enumerate(items):
            key = item.get('filename', '')
            original_name = item.get('original_name', key)
            tags = item.get('tags', [])
            transcript = item.get('transcript', '')[:15000]  # Increased to 15000 chars for better context
            
            context = f"[{idx}] File: {original_name}\n"
            if tags:
                context += f"    Tags: {', '.join(tags)}\n"
            if transcript:
                # Show first part of transcript
                context += f"    Transcript excerpt: {transcript[:500]}...\n"
            context += "\n"
            
            numbered_context.append(context)
            
            file_context.append({
                'idx': idx,
                'key': key,
                'name': original_name,
                'tags': tags
            })
        
        all_context = "".join(numbered_context)
        
        # PASS 1: STRICT/PRECISE SEARCH
        print("[QWEN SEARCH] Pass 1: Strict search...")
        strict_prompt = f"""You are a precise search agent. Find files that contain direct quotes, specific mentions, or very similar wording to the user's query.

Here is a numbered list of all files with their metadata:

{all_context}

User Query: {user_query}

Your task: Identify ONLY files that contain direct quotes, specific phrases, or very closely related content to the user's query. Be strict - only include files with clear, direct relevance. Ignore tangential or loosely related files. Return ONLY the numbers (in square brackets) of matching files, one per line. For example: [0] [2] [5]
If no files have direct relevance, return "NO_MATCHES"."""

        strict_indices = _perform_qwen_search(strict_prompt, api_key, temperature=0.2)
        
        # If we got any results from strict search, return those
        if len(strict_indices) > 0:
            print(f"[QWEN SEARCH] Pass 1 returned {len(strict_indices)} results, using those")
            return _build_search_results(strict_indices, file_context)
        
        # PASS 2: LENIENT SEARCH
        print("[QWEN SEARCH] Pass 1 found nothing, doing Pass 2: Lenient search...")
        lenient_prompt = f"""You are a lenient search agent. The user is looking for files matching their natural language query. Be GENEROUS - include files that are even tangentially related or have semantic overlap with the query.

Here is a numbered list of all files with their metadata:

{all_context}

User Query: {user_query}

Your task: Identify which files match or relate to the user's query based on content, tags, and transcripts. Be lenient - include files with semantic overlap, even if not exact matches. Return ONLY the numbers (in square brackets) of matching files, one per line. For example: [0] [2] [5]
If truly no files match, return "NO_MATCHES"."""

        lenient_indices = _perform_qwen_search(lenient_prompt, api_key, temperature=0.5)
        
        if len(lenient_indices) > 0:
            print(f"[QWEN SEARCH] Pass 2 returned {len(lenient_indices)} results")
            return _build_search_results(lenient_indices, file_context)
        
        # PASS 3: TOPIC-BASED SEARCH (Most Lenient)
        print("[QWEN SEARCH] Pass 2 found nothing, doing Pass 3: Topic-based search...")
        topic_prompt = f"""You are a very lenient topic-matching search agent. The user is interested in files related to certain topics or general areas. Find ANY files that share a general topic, subject area, or broad theme with the user's query.

Here is a numbered list of all files with their metadata:

{all_context}

User Query: {user_query}

Your task: Identify ANY files that relate to the general topics or subject areas mentioned in the user's query, even if very loosely connected. Be extremely generous - include files that share any related topic, theme, or general area of interest. Return ONLY the numbers (in square brackets) of matching files, one per line. For example: [0] [2] [5]
If no files relate to the topic at all, return "NO_MATCHES"."""

        topic_indices = _perform_qwen_search(topic_prompt, api_key, temperature=0.7)
        
        if len(topic_indices) == 0:
            print("[QWEN SEARCH] All three passes found no matches")
            return []
        
        print(f"[QWEN SEARCH] Pass 3 returned {len(topic_indices)} results")
        return _build_search_results(topic_indices, file_context)
        
    except Exception as e:
        print(f"[QWEN SEARCH] Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def _perform_qwen_search(prompt: str, api_key: str, temperature: float = 0.3):
    """Helper function to perform a single Qwen search pass and return list of indices"""
    try:
        response = requests.post(
            "https://api.featherless.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 500
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            if 'choices' in result and len(result['choices']) > 0:
                response_text = result['choices'][0]['message']['content'].strip()
                print(f"[QWEN SEARCH] Response: {response_text}")
                
                if "NO_MATCHES" in response_text.upper():
                    return []
                
                # Parse indices from response (e.g., "[0]", "[2]", "[5]")
                import re
                indices = [int(m) for m in re.findall(r'\[(\d+)\]', response_text)]
                return indices
        else:
            print(f"[QWEN SEARCH] Featherless API error: {response.status_code}")
            return []
    except Exception as e:
        print(f"[QWEN SEARCH] Error in search: {e}")
        return []

def _build_search_results(indices: list, file_context: list):
    """Helper function to build result objects from file indices"""
    global s3_client, AWS_BUCKET
    matching_files = []
    for f in file_context:
        if f['idx'] in indices:
            matching_files.append({
                "key": f['key'],
                "name": f['name'],
                "tags": f['tags'],
                "url": s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': AWS_BUCKET, 'Key': f['key']},
                    ExpiresIn=3600
                ) if s3_client else ''
            })
    print(f"[QWEN SEARCH] Returning {len(matching_files)} files")
    return matching_files