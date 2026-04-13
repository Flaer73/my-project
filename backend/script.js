const API_BASE = (window.location.origin.endsWith(':8000') ? window.location.origin : 'http://localhost:8000');
const API_GENERATE = `${API_BASE}/api/generate`;
const API_SURVEYS = `${API_BASE}/api/surveys`;

let currentSurveyId = null;

async function loadHistory() {
    const historyList = document.getElementById('historyList');
    historyList.innerHTML = 'Загрузка...';
    try {
        const res = await fetch(`${API_SURVEYS}`);
        if (!res.ok) throw new Error(`Ошибка ${res.status}`);
        const items = await res.json();

        if (!items || !items.length) {
            historyList.innerHTML = '<p style="color:#666">История пуста</p>';
            return;
        }

        historyList.innerHTML = items.map(item => {
            const date = item.created_at ? new Date(item.created_at).toLocaleString('ru-RU') : '—';
            let questionsCount = 0;
            let category = '—';
            try {
                const gen = item.generated_result;
                const parsed = (typeof gen === 'string') ? JSON.parse(gen) : gen;
                questionsCount = parsed.questions ? parsed.questions.length : 0;
                category = parsed.category || '—';
            } catch(e) {}
            return `
            <div style="border-bottom:1px solid #eee; padding: 0.75rem 0;">
                <div style="display:flex; justify-content:space-between; align-items:start;">
                <div>
                    <strong>${escapeHtml(category)}</strong><br>
                    <small style="color:#666">${escapeHtml(date)} | Вопросов: ${questionsCount}</small>
                    ${item.hint ? `<br><small style="color:#999">Подсказка: ${escapeHtml(item.hint)}</small>` : ''}
                </div>
                <button class="secondary" style="padding:0.4rem 0.8rem; font-size:0.9rem;"
                    onclick="loadSurveyFromHistory(${item.id})">
                    Открыть
                </button>
                </div>
            </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Ошибка загрузки истории:', e);
        historyList.innerHTML = `<p style="color:#d32f2f">Ошибка: ${escapeHtml(e.message || String(e))}</p>`;
    }
}

async function loadSurveyFromHistory(id) {
    try {
        const res = await fetch(`${API_SURVEYS}/${id}`);
        if (!res.ok) throw new Error(`Ошибка ${res.status}`);
        const item = await res.json();

        let data;
        if (item.user_edited_result) {
            data = (typeof item.user_edited_result === 'string') ? JSON.parse(item.user_edited_result) : item.user_edited_result;
        } else {
            data = (typeof item.generated_result === 'string') ? JSON.parse(item.generated_result) : item.generated_result;
        }

        currentSurveyId = id;
        document.getElementById('jsonEditor').value = JSON.stringify(data, null, 2);
        renderResult(data, item.client_journey || '', item.hint || '');
        document.getElementById('result').classList.add('active');
        document.getElementById('result').scrollIntoView({behavior: 'smooth'});
    } catch (e) {
        console.error('Ошибка загрузки опроса:', e);
        alert('Не удалось загрузить опрос');
    }
}

async function generateSurvey() {
    const journeyEl = document.getElementById('journey');
    const hintEl = document.getElementById('hint');
    const errorEl = document.getElementById('error');
    const loadingEl = document.getElementById('loading');
    const resultEl = document.getElementById('result');

    errorEl.classList.remove('active');
    const journey = journeyEl.value.trim();
    const hint = hintEl.value.trim();

    if (!journey) {
        errorEl.textContent = 'Введите путь клиента';
        errorEl.classList.add('active');
        return;
    }

    loadingEl.classList.add('active');
    resultEl.classList.remove('active');
    document.getElementById('generateBtn').disabled = true;

    try {
        const response = await fetch(API_GENERATE, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ journey, hint })
        });
        if (!response.ok) {
            const err = await response.json().catch(()=>({}));
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }
        const data = await response.json();
        // API now returns survey_id along with result
        if (data.survey_id) currentSurveyId = data.survey_id;
        renderResult(data, journey, hint);
        resultEl.classList.add('active');
        // refresh history list
        await loadHistory();
    } catch (e) {
        errorEl.textContent = `${e.message || String(e)}`;
        errorEl.classList.add('active');
    } finally {
        loadingEl.classList.remove('active');
        document.getElementById('generateBtn').disabled = false;
    }
}

function renderResult(data, journey, hint) {
    if (!data || !Array.isArray(data.questions)) {
        alert('Модель вернула неожиданный формат. Проверьте логи.');
        console.error('Invalid result:', data);
        return;
    }
    document.getElementById('resCategory').textContent = data.category || '—';
    document.getElementById('resRelevance').textContent =
        (typeof data.relevance === 'number') ? (data.relevance * 100).toFixed(0) + '%' : '—';

    const tbody = document.querySelector('#questionsTable tbody');
    tbody.innerHTML = '';
    (data.questions || []).forEach((q, i) => {
        const row = tbody.insertRow();
        row.insertCell(0).textContent = i + 1;
        row.insertCell(1).textContent = q;
    });

    document.getElementById('promptPreview').textContent =
        `SYSTEM: [см. prompts.py]\n\nUSER: Путь: ${journey}\nПодсказка: ${hint || '—'}`;
    document.getElementById('jsonEditor').value = JSON.stringify(data, null, 2);
}

async function applyEdit() {
    try {
        const edited = JSON.parse(document.getElementById('jsonEditor').value);
        if (currentSurveyId) {
            const response = await fetch(`${API_SURVEYS}/${currentSurveyId}/edit`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ edited_result: edited })
            });
            if (response.ok) {
                alert('Правки применены и сохранены в базе');
                // refresh history to reflect changes
                await loadHistory();
            } else {
                const err = await response.json().catch(()=>({}));
                alert(`Правки применены локально, но не сохранены: ${err.detail || 'ошибка сервера'}`);
            }
        } else {
            alert('Правки применены (локально)');
        }
        renderResult(edited, '', '');
    } catch (e) {
        console.error('applyEdit error', e);
        alert('Некорректный JSON');
    }
}

function exportJSON() {
    try {
        const data = JSON.parse(document.getElementById('jsonEditor').value);
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `survey_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    } catch {
        alert('Не удалось экспортировать: проверьте JSON');
    }
}

// Utility to avoid XSS when inserting strings into HTML
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
}

// On load
window.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    document.getElementById('generateBtn').addEventListener('click', generateSurvey);
});
