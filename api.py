import fastapi


async def lifespan(app: FastAPI):
    print("Starting...")
    yield
    print("Stopped.")