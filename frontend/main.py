import os
import json
from typing import Optional, List, Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

import uvicorn

from ai_client import generate_survey_from_journey
from prompts import SYSTEM_PROMPT
import db  # предполагается асинхронный модуль, предложенный ранее

app = FastAPI(title="Bank Survey Generator MVP")

# CORS — по умолчанию разрешаем все (в продакшне ограничьте)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация БД при старте ( асинхронно )
@app.on_event("startup")
async def startup_event():
    await db.init_db()

class SurveyRequest(BaseModel):
    journey: Any
    hint: Optional[str] = None

class SurveyResponse(BaseModel):
    category: str
    relevance: float
    questions: List[str]

@app.post("/api/generate", response_model=SurveyResponse)
async def generate_survey(request: SurveyRequest):
    # Вызов LLM (асинхронный)
    try:
        result: Dict[str, Any] = await generate_survey_from_journey(request.journey, request.hint)
    except Exception as e:
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
        # Не ломаем отклик модели, но сообщаем об ошибке сохранения
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    return {**result, "survey_id": survey_id}

@app.get("/api/surveys")
async def list_surveys(limit: int = 50):
    """Получить список последних сгенерированных опросов."""
    try:
        surveys = await db.get_all_surveys(limit)
        return surveys
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/surveys/{survey_id}")
async def get_survey(survey_id: int):
    """Получить детали конкретного опроса."""
    try:
        survey = await db.get_survey_by_id(survey_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    return survey

@app.get("/api/surveys/export/csv")
async def export_surveys_csv():
    import csv, io

    try:
        surveys = await db.get_all_surveys(limit=500)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "category", "relevance", "questions_count", "hint"])

    for s in surveys:
        try:
            # ожидаем, что generated_result уже JSON (Postgres jsonb -> Python dict)
            gen = s.get("generated_result") if isinstance(s, dict) else None
            if isinstance(gen, str):
                gen = json.loads(gen)
            category = gen.get("category", "") if isinstance(gen, dict) else ""
            relevance = gen.get("relevance", "") if isinstance(gen, dict) else ""
            questions_count = len(gen.get("questions", [])) if isinstance(gen, dict) else ""
            writer.writerow([
                s.get("id"),
                s.get("created_at"),
                category,
                relevance,
                questions_count,
                s.get("hint") or ""
            ])
        except Exception:
            # пропускаем проблемные записи, но продолжаем формировать CSV
            continue

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM для корректного открытия в Excel
    return Response(content=csv_bytes, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=surveys.csv"})

class EditRequest(BaseModel):
    edited_result: Dict[str, Any]

@app.put("/api/surveys/{survey_id}/edit")
async def save_survey_edit(survey_id: int, request: EditRequest):
    """Сохраняет отредактированный пользователем результат."""
    try:
        success = await db.update_survey_edited_result(survey_id, request.edited_result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail="Survey not found")
    return {"status": "ok", "message": "Edit saved"}

# Отдаём статические файлы фронтенда из папки frontend рядом с этим main.py
app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "frontend"), html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host=os.getenv("API_HOST", "127.0.0.1"), port=int(os.getenv("API_PORT", "8000")), reload=True)