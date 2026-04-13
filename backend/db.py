import os
import json
import logging
import asyncio
from typing import Optional, List, Dict, Any

from sqlalchemy import Column, Integer, String, DateTime, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession

logger = logging.getLogger(__name__)

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


# Глобальные переменные для engine и session
_engine: Optional[AsyncEngine] = None
AsyncSessionLocal: Optional[sessionmaker] = None


def get_engine() -> AsyncEngine:
    """Ленивая инициализация async engine."""
    global _engine, AsyncSessionLocal
    if _engine is None:
        _engine = create_async_engine(DATABASE_URL, echo=False, future=True)
        AsyncSessionLocal = sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
        logger.info("Database engine initialized")
    return _engine


async def init_db():
    """Создаёт таблицы, если их нет. Вызывать при старте приложения."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")


async def _get_session() -> AsyncSession:
    """Получает сессию БД, инициализируя engine при необходимости."""
    global AsyncSessionLocal
    if AsyncSessionLocal is None:
        get_engine()
    return AsyncSessionLocal()


def _normalize_journey(journey: Any) -> Any:
    """Приводит journey к dict/list для сохранения в JSONB."""
    if isinstance(journey, (dict, list)):
        return journey
    if isinstance(journey, str):
        stripped = journey.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse journey as JSON: {stripped[:100]}")
                return journey
    return journey


async def save_survey(
    journey: Any,
    hint: Optional[str],
    result: Dict[str, Any],
    prompt: Optional[str] = None,
    edited_result: Optional[Dict[str, Any]] = None,
    model_name: Optional[str] = None
) -> int:
    """Сохраняет запись и возвращает её ID."""
    async with _get_session() as session:
        async with session.begin():
            survey = Survey(
                client_journey=_normalize_journey(journey),
                hint=hint,
                generated_result=result,
                prompt_used=prompt,
                user_edited_result=edited_result,
                model_name=model_name
            )
            session.add(survey)
        await session.refresh(survey)
        logger.info(f"Survey saved with id={survey.id}")
        return survey.id


async def get_all_surveys(limit: int = 50) -> List[Dict[str, Any]]:
    """Возвращает список последних записей."""
    async with _get_session() as session:
        result = await session.execute(
            text("SELECT * FROM surveys ORDER BY created_at DESC LIMIT :limit"),
            {"limit": limit}
        )
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]


async def get_survey_by_id(survey_id: int) -> Optional[Dict[str, Any]]:
    """Возвращает запись по ID или None."""
    async with _get_session() as session:
        result = await session.execute(
            text("SELECT * FROM surveys WHERE id = :id"),
            {"id": survey_id}
        )
        row = result.first()
        return dict(row._mapping) if row else None


async def update_survey_edited_result(
    survey_id: int,
    edited_result: Dict[str, Any]
) -> bool:
    """Обновляет user_edited_result. Возвращает True, если запись найдена."""
    async with _get_session() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    "UPDATE surveys SET user_edited_result = :uer, updated_at = NOW() "
                    "WHERE id = :id RETURNING id"
                ),
                {"uer": edited_result, "id": survey_id}
            )
            updated = result.first()
            if updated:
                logger.info(f"Survey {survey_id} edited result updated")
            return updated is not None


# === Синхронные обёртки (использовать с осторожностью) ===

def init_db_sync():
    return asyncio.run(init_db())


def save_survey_sync(*args, **kwargs):
    return asyncio.run(save_survey(*args, **kwargs))


def get_all_surveys_sync(limit: int = 50):
    return asyncio.run(get_all_surveys(limit))


def get_survey_by_id_sync(survey_id: int):
    return asyncio.run(get_survey_by_id(survey_id))


def update_survey_edited_result_sync(survey_id: int, edited_result: Dict[str, Any]):
    return asyncio.run(update_survey_edited_result(survey_id, edited_result))