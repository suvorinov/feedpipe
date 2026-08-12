let ws = null;
let isSyncing = false;


function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + window.location.host + '/ws');

    ws.onmessage = function(event) {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (e) {
            console.error('WS: невалидное сообщение', event.data);
            return;
        }

        if (data.type === 'status') {
            isSyncing = data.is_running;
            updateSyncStatus();
        }
        else if (data.type === 'sync_start') {
            isSyncing = true;
            updateSyncStatus();
        }
        else if (data.type === 'sync_complete') {
            isSyncing = false;
            updateSyncStatus();
            updateCounter(data.count);
            flashSyncButton();
            refreshFeedIfEmpty(data.count);
        }
        else if (data.type === 'sync_error') {
            isSyncing = false;
            updateSyncStatus();
        }
        else if (data.type === 'counter_update') {
            updateCountersFromBroadcast(data.inbox_count, data.later_count);
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
        statusEl.textContent = isEnglish ? 'SYNC IN PROGRESS...' : 'СИНХРОНИЗАЦИЯ...';
        statusEl.className = 'sync-status syncing';
        btnEl.disabled = true;
    } else {
        statusEl.textContent = isEnglish ? 'NEXT SYNC: 30 MIN' : 'СЛЕДУЮЩИЙ: ЧЕРЕЗ 30 МИН';
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

    const navInboxEl = document.getElementById('nav-tabs-inbox-count');
    if (navInboxEl) navInboxEl.textContent = count;
}

function decrementCounter() {
    const inboxEl = document.getElementById('inbox-count');
    if (inboxEl) {
        const current = parseInt(inboxEl.textContent) || 0;
        inboxEl.textContent = Math.max(0, current - 1);
    }

    const navInboxEl = document.getElementById('nav-tabs-inbox-count');
    if (navInboxEl) {
        const current = parseInt(navInboxEl.textContent) || 0;
        navInboxEl.textContent = Math.max(0, current - 1);
    }

    const navLaterEl = document.getElementById('nav-tabs-inbox-later');
    if (navLaterEl) {
        const current = parseInt(navLaterEl.textContent) || 0;
        navLaterEl.textContent = Math.max(0, current + 1);
    }
}

function incrementCounter() {
    const inboxEl = document.getElementById('inbox-count');
    if (inboxEl) {
        const current = parseInt(inboxEl.textContent) || 0;
        inboxEl.textContent = current + 1;
    }

    const navInboxEl = document.getElementById('nav-tabs-inbox-count');
    if (navInboxEl) {
        const current = parseInt(navInboxEl.textContent) || 0;
        navInboxEl.textContent = current + 1;
    }

    const navLaterEl = document.getElementById('nav-tabs-inbox-later');
    if (navLaterEl) {
        const current = parseInt(navLaterEl.textContent) || 0;
        navLaterEl.textContent = Math.max(0, current - 1);
    }
}

function updateCountersFromBroadcast(inbox, later) {
    const inboxEl = document.getElementById('inbox-count');
    if (inboxEl) inboxEl.textContent = inbox;

    const laterEl = document.getElementById('nav-tabs-inbox-later');
    if (laterEl) laterEl.textContent = later;
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

// После синхронизации, если в ленте показывалось пустое состояние,
// перерисовываем список статей, не трогая остальную страницу.
// Условия:
//   - лента ещё пустая (иначе ничего не делаем — читающий пользователь не дёргается);
//   - синк действительно принёс записи во Входящие (count > 0);
//   - мы на вкладке Входящие: отложенные синхронизация не наполняет.
function refreshFeedIfEmpty(inboxCount) {
    const feedList = document.getElementById('feed-list');
    if (!feedList || !feedList.querySelector('.empty-state')) return;
    if (inboxCount <= 0) return;
    if (document.documentElement.dataset.view !== 'inbox') return;

    htmx.ajax('GET', '/?view=inbox', {
        target: '#feed-list',
        swap: 'innerHTML',
    });
}

function changeLang(lang) {
    document.cookie = "feedpipe_lang=" + lang + ";path=/;max-age=31536000";
    window.location.href = '/?lang=' + lang;
}

function showFeedError(message) {
    const errorEl = document.getElementById('feed-error');
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.classList.add('visible');
        setTimeout(() => {
            errorEl.classList.remove('visible');
        }, 5000);
    }
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
