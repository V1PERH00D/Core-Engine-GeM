from fastapi import FastAPI
from fastapi import UploadFile
from pathlib import Path
import uuid
from app.database import SessionLocal, Evaluation
from app.entity_extraction.main import app as entity_extraction_router

app = FastAPI()
app.include_router(entity_extraction_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}

from app.database import engine
from sqlalchemy import text

@app.get("/db-check")
def db_check():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        return {"db_connected": result.scalar() == 1}

from app.database import Base, engine

Base.metadata.create_all(bind=engine)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

from app.tasks import process_evaluation
@app.post("/evaluations/start")
async def start_evaluation(file: UploadFile):
    evaluation_id = uuid.uuid4()
    dest_path = UPLOAD_DIR / f"{evaluation_id}.zip"

    with open(dest_path, "wb") as out_file:
        while chunk := await file.read(1024 * 1024):
            out_file.write(chunk)

    db = SessionLocal()
    evaluation = Evaluation(
        id=evaluation_id,
        original_zip_name=file.filename,
        status="uploaded"
    )
    db.add(evaluation)
    db.commit()
    db.close()
    process_evaluation.delay(str(evaluation_id), str(dest_path))
    return {"evaluation_id": str(evaluation_id), "status": "uploaded"}