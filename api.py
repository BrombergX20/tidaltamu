from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel

class file_upload(BaseModel):
    url: str
    type: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting...")
    yield
    print("Shutdown")


app = FastAPI(lifespan=lifespan)

@app.post("/add_doc")
def add_doc(doc: file_upload):

    if doc.type in ["pdf", "docx", "txt"]:
        return {"message": f"Document added successfully, type: {doc.type}"}
    
    elif doc.type in ["mp4", "avi", "mkv"]:
        return {"message": f"Video added successfully, type: {doc.type}"}
    
    elif doc.type in ["mp3", "wav", "aac"]:
        return {"message": f"Audio added successfully, type: {doc.type}"}
    

if __name__ == "__main__":
    file = file_upload(url="http://example.com/document.pdf", type="")
    print(add_doc(file))