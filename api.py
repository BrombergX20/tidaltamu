from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from db_upload import upload_file

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting...")
    os.makedirs("temp/files/", exist_ok=True)
    os.makedirs("temp/videos/", exist_ok=True)
    os.makedirs("temp/audios/", exist_ok=True)
    yield
    print("Shutdown")

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/add_doc")
async def add_doc(file: UploadFile = File(...), type: str = Form(...) ):
    if type in ["pdf", "docx", "txt"]:
        print("type: ", type)
        save_path = f"temp/files/{file.filename}"
        with open(save_path, "wb") as f:
            f.write(await file.read())
        upload_return = upload_file(save_path)
        if upload_return.keys() == ["key", "name", "url", "content_type"]:
            return {"message": f"Document added successfully, type: {type}", "path": save_path}
        
        return {"Message": "Failed to upload document"}
    
    elif type in ["mp4", "avi", "mkv"]:
        print("type: ", type)
        save_path = f"temp/videos/{file.filename}"
        with open(save_path, "wb") as f:
            f.write(await file.read())
        upload_return = upload_file(save_path)
        if upload_return.keys() == ["key", "name", "url", "content_type"]:
            return {"message": f"Video added successfully, type: {type}", "path": save_path}
        
        return {"Message": "Failed to upload video file"}
    
    elif type in ["mp3", "wav", "aac"]:
        print("type: ", type)
        save_path = f"temp/audios/{file.filename}"
        with open(save_path, "wb") as f:
            f.write(await file.read())
        upload_return = upload_file(save_path)
        if upload_return.keys() == ["key", "name", "url", "content_type"]:
            return {"message": f"Audio added successfully, type: {type}", "path": save_path}
        
        return {"Message": "Failed to upload audio file"}

    return {"message": "Unknown file type"}

