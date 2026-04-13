/**
 * Банк: Генератор персонализированных опросов (фронтенд)
 * MVP-версия с базовой валидацией и обработкой ошибок
 */

// === Конфигурация ===
// Приоритет: 1) data-атрибут в HTML, 2) относительный путь, 3) fallback
const IS_FILE_PROTOCOL = window.location.protocol === 'file:';
const API_BASE = IS_FILE_PROTOCOL ? 'http://localhost:8000' : '';

const API_GENERATE = `${API_BASE}/api/generate`;
const API_SURVEYS = `${API_BASE}/api/surveys`;
const API_EXPORT_CSV = `${API_BASE}/api/surveys/export/csv`;

let currentSurveyId = null;
let lastGeneratedJourney = '';
let lastGeneratedHint = '';

// === Утилиты ===

/**
 * Экранирует HTML-специальные символы для защиты от XSS
 */
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Показывает сообщение об ошибке в интерфейсе
 */
function showError(message) {
    const errorEl = document.getElementById('error');
    errorEl.textContent = message;
    errorEl.classList.add('active');
    // Авто-скрытие через 10 секунд
    setTimeout(() => errorEl.classList.remove('active'), 10000);
}

/**
 * Показывает/скрывает индикатор загрузки
 */
function setLoading(isLoading) {
    const loadingEl = document.getElementById('loading');
    const btn = document.getElementById('generateBtn');
    
    if (isLoading) {
        loadingEl.classList.add('active');
        btn.disabled = true;
        btn.innerHTML = '⏳ Генерация...';
    } else {
        loadingEl.classList.remove('active');
        btn.disabled = false;
        btn.innerHTML = '✨ Сгенерировать опрос';
    }
}

/**
 * Валидирует JSON-строку и возвращает { valid: boolean, error?: string, data?: any }
 */
function validateJSONString(jsonString) {
    try {
        const data = JSON.parse(jsonString);
        return { valid: true, data };
    } catch (e) {
        return { valid: false, error: e.message };
    }
}

/**
 * Проверяет структуру результата опроса
 */
function validateSurveyStructure(data) {
    const errors = [];
    
    if (!data || typeof data !== 'object') {
        errors.push('Результат должен быть объектом');
        return errors;
    }
    
    if (typeof data.category !== 'string' || !data.category.trim()) {
        errors.push('Поле "category" должно быть непустой строкой');
    }
    
    if (typeof data.relevance !== 'number' || data.relevance < 0 || data.relevance > 1) {
        errors.push('Поле "relevance" должно быть числом от 0.0 до 1.0');
    }
    
    if (!Array.isArray(data.questions) || data.questions.length === 0) {
        errors.push('Поле "questions" должно быть непустым массивом');
    } else {
        data.questions.forEach((q, i) => {
            if (typeof q !== 'string' || !q.trim()) {
                errors.push(`Вопрос #${i + 1} должен быть непустой строкой`);
            }
        });
    }
    
    return errors;
}

/**
 * Форматирует дату в читаемый вид
 */
function formatDate(dateString) {
    if (!dateString) return '—';
    try {
        return new Date(dateString).toLocaleString('ru-RU', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return dateString;
    }
}

// === Основные функции ===

/**
 * Загружает и отображает историю опросов
 */
async function loadHistory() {
    const historyList = document.getElementById('historyList');
    historyList.innerHTML = '<p class="empty-state">Загрузка...</p>';
    
    try {
        const res = await fetch(`${API_SURVEYS}?limit=20`);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Ошибка сервера: ${res.status}`);
        }
        
        const items = await res.json();
        
        if (!items || !items.length) {
            historyList.innerHTML = '<p class="empty-state">История пуста. Сгенерируйте первый опрос.</p>';
            return;
        }
        
        historyList.innerHTML = items.map(item => {
            const date = formatDate(item.created_at);
            let questionsCount = 0;
            let category = '—';
            let relevance = null;
            
            // Безопасный парсинг результата
            try {
                const gen = item.generated_result;
                const parsed = (typeof gen === 'string') ? JSON.parse(gen) : gen;
                if (parsed && typeof parsed === 'object') {
                    category = escapeHtml(parsed.category || '—');
                    relevance = parsed.relevance;
                    questionsCount = Array.isArray(parsed.questions) ? parsed.questions.length : 0;
                }
            } catch (e) {
                console.warn('Failed to parse generated_result:', e);
            }
            
            const hint = item.hint ? `<div class="history-hint">💡 ${escapeHtml(item.hint)}</div>` : '';
            const relevanceBadge = relevance !== null 
                ? `<span style="margin-left:0.5rem; padding:0.2rem 0.5rem; background:${relevance >= 0.8 ? '#d1fae5' : '#fef3c7'}; border-radius:4px; font-size:0.85rem;">${Math.round(relevance * 100)}%</span>` 
                : '';
            
            return `
            <div class="history-item" role="listitem">
                <div class="history-meta">
                    <div>
                        <strong>📁 ${category}</strong>${relevanceBadge}
                        <div style="color:#6b7280; font-size:0.9rem; margin:0.25rem 0;">
                            🕐 ${escapeHtml(date)} | ❓ Вопросов: ${questionsCount}
                        </div>
                        ${hint}
                    </div>
                    <button 
                        type="button"
                        class="btn btn-outline" 
                        style="padding:0.4rem 0.8rem; font-size:0.9rem;"
                        onclick="loadSurveyFromHistory(${item.id})"
                        aria-label="Открыть опрос #${item.id}"
                    >
                        Открыть
                    </button>
                </div>
            </div>
            `;
        }).join('');
        
    } catch (e) {
        console.error('Ошибка загрузки истории:', e);
        historyList.innerHTML = `<p style="color:#b91c1c; padding:1rem;">❌ Ошибка: ${escapeHtml(e.message || String(e))}</p>`;
    }
}

/**
 * Загружает конкретный опрос из истории и отображает его
 */
async function loadSurveyFromHistory(id) {
    try {
        const res = await fetch(`${API_SURVEYS}/${id}`);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Ошибка: ${res.status}`);
        }
        
        const item = await res.json();
        
        // Определяем, какой результат показывать: отредактированный или сгенерированный
        let data;
        if (item.user_edited_result) {
            data = (typeof item.user_edited_result === 'string') 
                ? JSON.parse(item.user_edited_result) 
                : item.user_edited_result;
        } else {
            data = (typeof item.generated_result === 'string') 
                ? JSON.parse(item.generated_result) 
                : item.generated_result;
        }
        
        // Обновляем состояние
        currentSurveyId = id;
        lastGeneratedJourney = item.client_journey || '';
        lastGeneratedHint = item.hint || '';
        
        // Отображаем результат
        document.getElementById('jsonEditor').value = JSON.stringify(data, null, 2);
        renderResult(data, lastGeneratedJourney, lastGeneratedHint);
        
        // Показываем секцию результата и прокручиваем к ней
        const resultSection = document.getElementById('result');
        resultSection.classList.add('active');
        resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        
        // Обновляем бейдж ID
        document.getElementById('resSurveyId').textContent = id;
        document.getElementById('surveyIdBadge').style.display = 'inline-flex';
        
    } catch (e) {
        console.error('Ошибка загрузки опроса:', e);
        showError(`Не удалось загрузить опрос #${id}: ${e.message}`);
    }
}

/**
 * Генерирует новый опрос по данным из формы
 */
async function generateSurvey() {
    const journeyEl = document.getElementById('journey');
    const hintEl = document.getElementById('hint');
    
    // Скрываем предыдущие сообщения
    document.getElementById('error').classList.remove('active');
    document.getElementById('jsonError').style.display = 'none';
    
    const journey = journeyEl.value.trim();
    const hint = hintEl.value.trim();
    
    // Валидация ввода
    if (!journey) {
        showError('⚠️ Введите путь клиента');
        journeyEl.focus();
        return;
    }
    
    // UI: показываем загрузку
    setLoading(true);
    document.getElementById('result').classList.remove('active');
    
    try {
        const response = await fetch(API_GENERATE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ journey, hint })
        });
        
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `Ошибка сервера: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Сохраняем контекст для последующих операций
        currentSurveyId = data.survey_id || null;
        lastGeneratedJourney = journey;
        lastGeneratedHint = hint;
        
        // Отображаем результат
        renderResult(data, journey, hint);
        
        // Показываем секцию результата
        document.getElementById('result').classList.add('active');
        document.getElementById('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
        
        // Обновляем историю
        await loadHistory();
        
        // Показываем успешный статус
        if (data.survey_id) {
            document.getElementById('resSurveyId').textContent = data.survey_id;
            document.getElementById('surveyIdBadge').style.display = 'inline-flex';
        }
        
    } catch (e) {
        console.error('Ошибка генерации:', e);
        showError(`❌ ${e.message || 'Неизвестная ошибка при генерации'}`);
    } finally {
        setLoading(false);
    }
}

/**
 * Отображает результат генерации в интерфейсе
 */
function renderResult(data, journey, hint) {
    // Базовая валидация
    if (!data || !Array.isArray(data.questions)) {
        showError('⚠️ Модель вернула неожиданный формат. Проверьте логи сервера.');
        console.error('Invalid result structure:', data);
        return;
    }
    
    // Заполняем метаданные
    document.getElementById('resCategory').textContent = data.category || '—';
    
    const relevance = data.relevance;
    document.getElementById('resRelevance').textContent = 
        (typeof relevance === 'number' && relevance >= 0 && relevance <= 1) 
            ? `${Math.round(relevance * 100)}%` 
            : '—';
    
    // Заполняем таблицу вопросов
    const tbody = document.querySelector('#questionsTable tbody');
    tbody.innerHTML = '';
    
    if (data.questions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center; color:#6b7280; padding:1rem;">Вопросы не сгенерированы</td></tr>';
    } else {
        data.questions.forEach((q, i) => {
            const row = tbody.insertRow();
            row.insertCell(0).textContent = i + 1;
            row.insertCell(1).textContent = q;
        });
    }
    
    // Показываем промпт для отладки
    document.getElementById('promptPreview').textContent = 
`SYSTEM: [см. prompts.py]

USER: Путь клиента:
${journey || '—'}

${hint ? `Подсказка: ${hint}` : ''}`;
    
    // Заполняем JSON-редактор
    document.getElementById('jsonEditor').value = JSON.stringify(data, null, 2);
    
    // Скрываем ошибку редактора, если была
    document.getElementById('jsonError').style.display = 'none';
}

/**
 * Применяет правки из JSON-редактора и сохраняет на сервер
 */
async function applyEdit() {
    const editor = document.getElementById('jsonEditor');
    const errorEl = document.getElementById('jsonError');
    
    // Валидация JSON
    const validation = validateJSONString(editor.value);
    if (!validation.valid) {
        errorEl.textContent = `❌ Ошибка JSON: ${validation.error}`;
        errorEl.style.display = 'block';
        errorEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
    }
    
    const edited = validation.data;
    
    // Валидация структуры опроса
    const structErrors = validateSurveyStructure(edited);
    if (structErrors.length > 0) {
        errorEl.innerHTML = `❌ Ошибка структуры:<br>${structErrors.map(e => `• ${escapeHtml(e)}`).join('<br>')}`;
        errorEl.style.display = 'block';
        errorEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
    }
    
    errorEl.style.display = 'none';
    
    try {
        if (currentSurveyId) {
            // Сохраняем на сервер
            const response = await fetch(`${API_SURVEYS}/${currentSurveyId}/edit`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ edited_result: edited })
            });
            
            if (response.ok) {
                // Показываем успех
                const successEl = document.getElementById('error');
                successEl.textContent = '✅ Правки сохранены в базе';
                successEl.className = 'alert alert-success active';
                setTimeout(() => successEl.classList.remove('active'), 5000);
                
                // Обновляем историю
                await loadHistory();
            } else {
                const err = await response.json().catch(() => ({}));
                showError(`⚠️ Правки не сохранены: ${err.detail || 'ошибка сервера'}`);
            }
        } else {
            // Только локальное применение (без ID)
            const successEl = document.getElementById('error');
            successEl.textContent = '✅ Правки применены локально (не сохранено в БД)';
            successEl.className = 'alert alert-success active';
            setTimeout(() => successEl.classList.remove('active'), 5000);
        }
        
        // Обновляем отображение
        renderResult(edited, lastGeneratedJourney, lastGeneratedHint);
        
    } catch (e) {
        console.error('applyEdit error:', e);
        showError(`❌ Ошибка при сохранении: ${e.message}`);
    }
}

/**
 * Экспортирует текущий результат в JSON-файл
 */
function exportJSON() {
    const editor = document.getElementById('jsonEditor');
    const validation = validateJSONString(editor.value);
    
    if (!validation.valid) {
        alert(`❌ Не удалось экспортировать: ошибка JSON\n${validation.error}`);
        return;
    }
    
    try {
        const blob = new Blob([JSON.stringify(validation.data, null, 2)], { 
            type: 'application/json;charset=utf-8' 
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Имя файла: survey_ID_timestamp.json или survey_timestamp.json
        const idPart = currentSurveyId ? `_${currentSurveyId}` : '';
        a.download = `survey${idPart}_${Date.now()}.json`;
        
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
    } catch (e) {
        console.error('exportJSON error:', e);
        alert('❌ Не удалось создать файл для экспорта');
    }
}

/**
 * Проверяет JSON в редакторе и показывает результат
 */
function validateJSON() {
    const editor = document.getElementById('jsonEditor');
    const errorEl = document.getElementById('jsonError');
    
    const validation = validateJSONString(editor.value);
    
    if (validation.valid) {
        const structErrors = validateSurveyStructure(validation.data);
        if (structErrors.length === 0) {
            errorEl.textContent = '✅ JSON валиден и соответствует ожидаемой структуре';
            errorEl.className = 'alert alert-success';
        } else {
            errorEl.innerHTML = `⚠️ JSON валиден, но структура не соответствует:<br>${structErrors.map(e => `• ${escapeHtml(e)}`).join('<br>')}`;
            errorEl.className = 'alert alert-error';
        }
    } else {
        errorEl.textContent = `❌ Ошибка JSON: ${validation.error}`;
        errorEl.className = 'alert alert-error';
    }
    
    errorEl.style.display = 'block';
}

/**
 * Экспорт истории в CSV
 */
async function exportHistoryCSV() {
    try {
        const response = await fetch(API_EXPORT_CSV);
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `Ошибка: ${response.status}`);
        }
        
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `surveys_export_${new Date().toISOString().split('T')[0]}.csv`;
        
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
    } catch (e) {
        console.error('CSV export error:', e);
        showError(`❌ Ошибка экспорта CSV: ${e.message}`);
    }
}

// === Инициализация ===

document.addEventListener('DOMContentLoaded', () => {
    // Привязка обработчиков
    document.getElementById('generateBtn').addEventListener('click', generateSurvey);
    
    // Горячие клавиши: Ctrl+Enter для генерации
    document.getElementById('journey').addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') {
            e.preventDefault();
            generateSurvey();
        }
    });
    
    // Авто-валидация JSON при редактировании (debounce)
    let validateTimeout;
    document.getElementById('jsonEditor').addEventListener('input', () => {
        clearTimeout(validateTimeout);
        validateTimeout = setTimeout(() => {
            const validation = validateJSONString(document.getElementById('jsonEditor').value);
            const errorEl = document.getElementById('jsonError');
            if (!validation.valid && errorEl.style.display === 'none') {
                errorEl.textContent = `⚠️ Ошибка JSON: ${validation.error}`;
                errorEl.className = 'alert alert-error';
                errorEl.style.display = 'block';
            } else if (validation.valid) {
                errorEl.style.display = 'none';
            }
        }, 500);
    });
    
    // Загрузка истории при старте
    loadHistory();
    
    // Логирование для отладки
    console.log('🚀 Stupnikov Alex frontend loaded');
    console.log(`📡 API Base: ${API_BASE || '(relative)'}`);
});
