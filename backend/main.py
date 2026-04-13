import os
import json
import logging
from typing import Optional, List, Any, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import uvicorn

from ai_client import generate_survey_from_journey
from prompts import SYSTEM_PROMPT
import db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bank Survey Generator MVP")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Pydantic модели ===

class SurveyRequest(BaseModel):
    journey: Any
    hint: Optional[str] = None


class SurveyResponse(BaseModel):
    category: str
    relevance: float = Field(ge=0.0, le=1.0)
    questions: List[str]
    survey_id: Optional[int] = None


class EditRequest(BaseModel):
    edited_result: Dict[str, Any]


# === События приложения ===

@app.on_event("startup")
async def startup_event():
    await db.init_db()
    logger.info("Application startup complete")


# === Эндпоинты ===

@app.post("/api/generate", response_model=SurveyResponse)
async def generate_survey(request: SurveyRequest):
    """Генерирует опрос на основе пути клиента."""
    try:
        result: Dict[str, Any] = await generate_survey_from_journey(
            request.journey,
            request.hint
        )
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"AI service error: {e}")
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {e}")
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=500, detail=f"Invalid model response: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in generate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    # Сохранение в БД
    try:
        survey_id = await db.save_survey(
            journey=request.journey,
            hint=request.hint,
            result=result,
            prompt=SYSTEM_PROMPT,
            edited_result=None,
            model_name=os.getenv("LM_MODEL_NAME", "local-model")
        )
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    return SurveyResponse(
        category=result["category"],
        relevance=result["relevance"],
        questions=result["questions"],
        survey_id=survey_id
    )


@app.get("/api/surveys")
async def list_surveys(limit: int = 50):
    """Получить список последних сгенерированных опросов."""
    try:
        surveys = await db.get_all_surveys(limit)
        return surveys
    except Exception as e:
        logger.error(f"Error listing surveys: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/surveys/{survey_id}")
async def get_survey(survey_id: int):
    """Получить детали конкретного опроса."""
    try:
        survey = await db.get_survey_by_id(survey_id)
    except Exception as e:
        logger.error(f"Error fetching survey {survey_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return survey


@app.get("/api/surveys/export/csv")
async def export_surveys_csv():
    """Экспорт опросов в CSV-формате."""
    import csv
    import io

    try:
        surveys = await db.get_all_surveys(limit=500)
    except Exception as e:
        logger.error(f"Error exporting surveys: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "category", "relevance", "questions_count", "hint"])

    for s in surveys:
        try:
            gen = s.get("generated_result")
            if isinstance(gen, str):
                gen = json.loads(gen)
            
            category = gen.get("category", "") if isinstance(gen, dict) else ""
            relevance = gen.get("relevance", "") if isinstance(gen, dict) else ""
            questions_count = len(gen.get("questions", [])) if isinstance(gen, dict) else 0
            
            writer.writerow([
                s.get("id"),
                s.get("created_at"),
                category,
                relevance,
                questions_count,
                s.get("hint") or ""
            ])
        except Exception as e:
            logger.warning(f"Skipping survey due to error: {e}")
            continue

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=surveys.csv"}
    )


@app.put("/api/surveys/{survey_id}/edit")
async def save_survey_edit(survey_id: int, request: EditRequest):
    """Сохраняет отредактированный пользователем результат."""
    try:
        success = await db.update_survey_edited_result(survey_id, request.edited_result)
    except Exception as e:
        logger.error(f"Error updating survey {survey_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    if not success:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    return {"status": "ok", "message": "Edit saved"}


# === Статические файлы (фронтенд) ===

frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists() and frontend_path.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
    logger.info(f"Frontend mounted from {frontend_path}")
else:
    @app.get("/")
    async def root():
        return {
            "message": "Bank Survey Generator API is running",
            "docs": "/docs",
            "note": "Frontend not found — place your static files in ./frontend"
        }
    logger.warning("Frontend directory not found — API only mode")


# === Запуск ===

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("DEBUG_MODE", "false").lower() == "true"
    )