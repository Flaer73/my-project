import os
import json
import asyncio
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, DateTime, func, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mydb")

Base = declarative_base()

class Survey(Base):
    __tablename__ = "surveys"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    client_journey = Column(JSONB, nullable=False)
    hint = Column(String, nullable=True)
    generated_result = Column(JSONB, nullable=False)
    prompt_used = Column(String, nullable=True)
    user_edited_result = Column(JSONB, nullable=True)
    model_name = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

# Async engine and session
_engine: Optional[AsyncEngine] = None
AsyncSessionLocal: Optional[sessionmaker] = None

def get_engine() -> AsyncEngine:
    global _engine, AsyncSessionLocal
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False, future=True)
        AsyncSessionLocal = sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine

async def init_db():
    """
    Создаёт таблицы, если их нет. Вызывать при старте приложения.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def _get_session() -> AsyncSession:
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        get_engine()
    return AsyncSessionLocal()

# Совместимые с вашим прежним интерфейсом функции (асинхронные)

async def save_survey(
    journey: Any,
    hint: Optional[str],
    result: Dict[str, Any],
    prompt: Optional[str] = None,
    edited_result: Optional[Dict[str, Any]] = None,
    model_name: Optional[str] = None
) -> int:
    """
    Сохраняет запись и возвращает id (int).
    journey может быть dict или строкой; сохраняется в JSONB.
    """
    async with _get_session() as session:
        async with session.begin():
            survey = Survey(
                client_journey=journey if isinstance(journey, (dict, list)) else json.loads(journey) if isinstance(journey, str) and (journey.strip().startswith("{") or journey.strip().startswith("[")) else journey,
                hint=hint,
                generated_result=result,
                prompt_used=prompt,
                user_edited_result=edited_result,
                model_name=model_name
            )
            session.add(survey)
        await session.refresh(survey)
        return survey.id

async def get_all_surveys(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Возвращает список последних записей в виде list[dict].
    """
    async with _get_session() as session:
        q = await session.execute(
            text("SELECT * FROM surveys ORDER BY created_at DESC LIMIT :limit"),
            {"limit": limit}
        )
        rows = q.fetchall()
        # Преобразуем SQLAlchemy Row -> dict
        result = []
        for row in rows:
            # row is a Row object with columns in order; map by keys if available
            d = dict(row._mapping)
            result.append(d)
        return result

async def get_survey_by_id(survey_id: int) -> Optional[Dict[str, Any]]:
    async with _get_session() as session:
        q = await session.execute(
            text("SELECT * FROM surveys WHERE id = :id"),
            {"id": survey_id}
        )
        row = q.first()
        return dict(row._mapping) if row else None

async def update_survey_edited_result(survey_id: int, edited_result: Dict[str, Any]) -> bool:
    async with _get_session() as session:
        async with session.begin():
            q = await session.execute(
                text("UPDATE surveys SET user_edited_result = :uer, updated_at = NOW() WHERE id = :id RETURNING id"),
                {"uer": edited_result, "id": survey_id}
            )
            updated = q.first()
            return updated is not None

# Синхронные обёртки (если остальной код остаётся синхронным)
def init_db_sync():
    return asyncio.get_event_loop().run_until_complete(init_db())

def save_survey_sync(*args, **kwargs):
    return asyncio.get_event_loop().run_until_complete(save_survey(*args, **kwargs))

def get_all_surveys_sync(limit: int = 50):
    return asyncio.get_event_loop().run_until_complete(get_all_surveys(limit))

def get_survey_by_id_sync(survey_id: int):
    return asyncio.get_event_loop().run_until_complete(get_survey_by_id(survey_id))

def update_survey_edited_result_sync(survey_id: int, edited_result: Dict[str, Any]):
    return asyncio.get_event_loop().run_until_complete(update_survey_edited_result(survey_id, edited_result))