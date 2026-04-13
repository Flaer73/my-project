import os
import json
import logging
from typing import Any, Union, Optional
import httpx

logger = logging.getLogger(__name__)

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
DEFAULT_TIMEOUT = 120.0

from prompts import SYSTEM_PROMPT


def _clean_model_response(content: str) -> str:
    """Извлекает JSON из ответа модели, удаляя markdown-блоки."""
    cleaned = content.strip()
    
    # Убираем блоки ```json ... ``` или ``` ... ```
    if "```json" in cleaned:
        try:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        except Exception:
            pass
    elif "```" in cleaned:
        try:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
        except Exception:
            pass
    
    return cleaned


def _validate_result(result: Any) -> None:
    """Валидирует структуру результата от модели."""
    if not isinstance(result, dict):
        raise ValueError("Ожидался JSON-объект (dict) в ответе модели")
    
    required_keys = {"category", "relevance", "questions"}
    missing = required_keys - result.keys()
    if missing:
        raise ValueError(f"Ответ модели не содержит обязательные поля: {missing}")
    
    if not isinstance(result["questions"], list):
        raise ValueError("Поле 'questions' должно быть списком строк")
    
    if not isinstance(result["relevance"], (int, float)) or not (0.0 <= result["relevance"] <= 1.0):
        raise ValueError("Поле 'relevance' должно быть числом от 0.0 до 1.0")


async def generate_survey_from_journey(
    journey: Union[str, dict],
    hint: Optional[str] = None
) -> dict:
    """
    Асинхронно вызывает LM Studio и возвращает десериализованный JSON-результат.
    
    Бросает:
        ConnectionError — если не удалось подключиться к LM Studio
        TimeoutError — если превышено время ожидания
        ValueError — если модель вернула невалидный JSON или структуру
        RuntimeError — при других ошибках сервера или сети
    """
    # Подготовка текста пути клиента
    if isinstance(journey, dict):
        journey_text = json.dumps(journey, ensure_ascii=False)
    else:
        journey_text = str(journey)

    user_content = f"Путь клиента: {journey_text}"
    if hint:
        user_content += f"\n\nДополнительная подсказка: {hint}"

    # Формирование запроса
    payload = {
        "model": os.getenv("LM_MODEL_NAME", "local-model"),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": float(os.getenv("LM_TEMPERATURE", "0.3")),
        "max_tokens": int(os.getenv("LM_MAX_TOKENS", "1024")),
        "stream": False
    }

    headers = {"Content-Type": "application/json"}
    timeout = httpx.Timeout(
        connect=10.0,
        read=float(os.getenv("LM_TIMEOUT", str(DEFAULT_TIMEOUT))),
        write=10.0,
        pool=10.0
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(LM_STUDIO_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.ConnectError as e:
            logger.error(f"Connection failed to {LM_STUDIO_URL}: {e}")
            raise ConnectionError(f"Не удалось подключиться к LM Studio по {LM_STUDIO_URL}")
        except httpx.ReadTimeout as e:
            logger.error(f"Read timeout: {e}")
            raise TimeoutError("Превышено время ожидания ответа от модели")
        except httpx.HTTPStatusError as e:
            body_preview = e.response.text[:1000].replace("\n", " ")
            logger.error(f"HTTP {e.response.status_code}: {body_preview}")
            raise RuntimeError(f"Ошибка от сервера LM Studio: {e.response.status_code}. Ответ: {body_preview}")
        except Exception as e:
            logger.error(f"Unexpected HTTP error: {e}", exc_info=True)
            raise RuntimeError(f"HTTP ошибка при обращении к LM Studio: {e}")

    # Извлечение контента из ответа
    try:
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"Unexpected response format: {data}")
        raise RuntimeError(f"Неожиданный формат ответа от модели: {e}")

    # Очистка от markdown
    cleaned = _clean_model_response(content)

    # Парсинг JSON
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        preview = cleaned[:500].replace("\n", " ")
        logger.error(f"JSON decode error: {e}. Preview: {preview}")
        raise ValueError(f"Модель вернула невалидный JSON: {preview}... Ошибка: {e}")

    # Валидация структуры
    _validate_result(result)
    logger.info(f"Successfully generated survey: category={result.get('category')}, relevance={result.get('relevance')}")
    
    return result


def generate_survey_from_journey_sync(
    journey: Union[str, dict],
    hint: Optional[str] = None
) -> dict:
    """Синхронная обёртка для вызова из синхронного кода."""
    import asyncio
    return asyncio.run(generate_survey_from_journey(journey, hint))