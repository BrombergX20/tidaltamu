from fastapi import FastAPI, UploadFile, File, Form
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting...")
    yield
    print("Shutdown")

app = FastAPI(lifespan=lifespan)

@app.post("/add_doc")
async def add_doc(file: UploadFile = File(...), type: str = Form(...) ):
    if type in ["pdf", "docx", "txt"]:
        return {"message": f"Document added successfully, type: {type}"}
    
    elif type in ["mp4", "avi", "mkv"]:
        return {"message": f"Video added successfully, type: {type}"}
    
    elif type in ["mp3", "wav", "aac"]:
        return {"message": f"Audio added successfully, type: {type}"}

    return {"message": "Unknown file type"}
