let ws = null;
let isSyncing = false;
let lastCount = 0;

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + window.location.host + '/ws');

    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.type === 'status') {
            isSyncing = data.is_running;
            lastCount = data.count;
            updateSyncStatus();
        }
        else if (data.type === 'sync_start') {
            isSyncing = true;
            updateSyncStatus();
        }
        else if (data.type === 'sync_complete') {
            isSyncing = false;
            lastCount = data.count;
            updateSyncStatus();
            updateCounter(data.count);
            flashSyncButton();
        }
        else if (data.type === 'sync_error') {
            isSyncing = false;
            updateSyncStatus();
        }
    };

    ws.onclose = function() {
        setTimeout(connectWebSocket, 3000);
    };
}

function updateSyncStatus() {
    const statusEl = document.getElementById('sync-status');
    const btnEl = document.getElementById('sync-btn');
    const isEnglish = document.body.dataset.lang === 'en';

    if (isSyncing) {
        statusEl.innerHTML = `
            <span class="sync-spinner"></span>
            ${isEnglish ? 'SYNC IN PROGRESS...' : 'СИНХРОНИЗАЦИЯ...'}
        `;
        statusEl.className = 'sync-status syncing';
        btnEl.disabled = true;
    } else {
        statusEl.innerHTML = `
            ${isEnglish ? 'NEXT SYNC: 30 MIN' : 'СЛЕДУЮЩИЙ: ЧЕРЕЗ 30 МИН'}
        `;
        statusEl.className = 'sync-status';
        btnEl.disabled = false;
    }
}

function updateCounter(count) {
    const el = document.getElementById('inbox-count');
    if (el) {
        el.textContent = count;
        el.style.color = '#00ff9d';
        setTimeout(() => el.style.color = '', 1000);
    }
}

function decrementCounter() {
    el = document.getElementById('inbox-count');
    if (el) {
        const current = parseInt(el.textContent) || 0;
        el.textContent = Math.max(0, current - 1);
    }

    el = document.getElementById('nav-tabs-inbox-count');
    if (el) {
        const current = parseInt(el.textContent) || 0;
        el.textContent = Math.max(0, current - 1);
    }

    el = document.getElementById('nav-tabs-inbox-later');
    if (el) {
        const current = parseInt(el.textContent) || 0;
        el.textContent = Math.max(0, current + 1);
    }
}

function animateRemove(el, className) {
    el.classList.add(className);
    setTimeout(() => el.remove(), 300);
}

function flashSyncButton() {
    const btn = document.getElementById('sync-btn');
    btn.style.background = 'var(--accent)';
    btn.style.color = 'var(--bg-base)';
    setTimeout(() => {
        btn.style.background = '';
        btn.style.color = '';
    }, 1000);
}

function changeLang(lang) {
    document.cookie = "feedpipe_lang=" + lang + ";path=/;max-age=31536000";
    window.location.href = '/?lang=' + lang;
}

// === ЛОГИКА ФИЛЬТРАЦИИ ФИДОВ ===
function filterFeeds() {
    const query = document.getElementById('feed-search').value.toLowerCase();
    const items = document.querySelectorAll('.feed-item');
    
    items.forEach(item => {
        const title = item.getAttribute('data-title');
        if (title.includes(query)) {
            item.classList.remove('hidden');
        } else {
            item.classList.add('hidden');
        }
    });
}

// === ЛОГИКА КНОПКИ "НАВЕРХ" ===
window.addEventListener('scroll', () => {
    const btnTop = document.getElementById('btn-top');
    // Если прокрутили больше 400 пикселей вниз — показываем стрелку
    if (window.scrollY > 600) {
        btnTop.classList.add('visible');
    } else {
        // Если наверху — прячем
        btnTop.classList.remove('visible');
    }
});

document.addEventListener('DOMContentLoaded', function() {
    connectWebSocket();
    updateSyncStatus();
});
