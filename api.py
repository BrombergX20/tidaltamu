from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

# Import functions from DB_stuff
from DB_stuff import upload_file, list_files, search_files

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Server...")
    os.makedirs("temp/files/", exist_ok=True)
    os.makedirs("temp/videos/", exist_ok=True)
    os.makedirs("temp/audios/", exist_ok=True)
    yield
    print("Server Shutdown")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/add_doc")
async def add_doc(file: UploadFile = File(...), type: str = Form(...)):
    # Determine folder based on type
    folder = "files"
    if type in ["mp4", "avi", "mkv"]:
        folder = "videos"
    elif type in ["mp3", "wav", "aac"]:
        folder = "audios"
        
    save_path = f"temp/{folder}/{file.filename}"
    
    # Save locally first
    with open(save_path, "wb") as f:
        f.write(await file.read())
    
    # Upload to S3 (Triggers AI + DB)
    try:
        result = upload_file(save_path)
        return {"message": "Success", "data": result}
    except Exception as e:
        return {"message": "Failed", "error": str(e)}
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)

@app.get("/list_docs")
async def get_all_docs():
    return list_files()

@app.get("/search")
async def search_docs(q: str):
    return search_files(q)