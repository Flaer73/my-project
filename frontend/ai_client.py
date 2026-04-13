import os
import json
from typing import Any, Union, Optional
import httpx

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions")
DEFAULT_TIMEOUT = 120.0

from prompts import SYSTEM_PROMPT  # ожидается строка

async def generate_survey_from_journey(journey: Union[str, dict], hint: Optional[str] = None) -> dict:
    """
    Асинхронно вызывает LM Studio и возвращает десериализованный JSON-результат.
    Бросает ConnectionError, TimeoutError, ValueError (некорректный JSON) или RuntimeError.
    """
    if isinstance(journey, dict):
        journey_text = json.dumps(journey, ensure_ascii=False)
    else:
        journey_text = str(journey)

    user_content = f"Путь клиента: {journey_text}"
    if hint:
        user_content += f"\n\nДополнительная подсказка: {hint}"

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

    timeout = float(os.getenv("LM_TIMEOUT", str(DEFAULT_TIMEOUT)))

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(LM_STUDIO_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.ConnectError:
            raise ConnectionError(f"Не удалось подключиться к LM Studio по {LM_STUDIO_URL}")
        except httpx.ReadTimeout:
            raise TimeoutError("Превышено время ожидания ответа от модели")
        except httpx.HTTPStatusError as e:
            # включаем текст ответа для отладки, но не слишком длинный
            body_preview = e.response.text[:1000]
            raise RuntimeError(f"Ошибка от сервера LM Studio: {e.response.status_code}. Ответ: {body_preview}")
        except Exception as e:
            raise RuntimeError(f"HTTP ошибка при обращении к LM Studio: {e}")

    # Попытка извлечь содержимое ответа в ожидаемом формате
    try:
        # ожидаем структуру { "choices": [ { "message": { "content": "..." } } ] }
        content = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(f"Неожиданный формат ответа от модели: {e}")

    # Обработать возможные блоки кода: ```json ... ``` или ```
    cleaned = content
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

    # Попытка распарсить JSON
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Включаем небольшой превью содержимого для ошибки
        preview = cleaned[:1000].replace("\n", " ")
        raise ValueError(f"Модель вернула невалидный JSON: {preview}... Ошибка парсинга: {e}")

    if not isinstance(result, dict):
        raise ValueError("Ожидался JSON-объект (dict) в ответе модели")

    return result

# Синхронная обёртка для удобства (если остальной код синхронный)
def generate\_survey\_from\_journey\_sync(journey: Union[str, dict], hint: Optional[str] = None) -> dict:
    import asyncio
    return asyncio.get\_event\_loop().run\_until\_complete(generate\_survey\_from\_journey(journey, hint))