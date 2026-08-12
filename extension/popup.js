const SERVER_KEY = 'serverUrl';
const DEFAULT_SERVER = 'http://192.168.0.9:8700';
const COOKIE_NAME = 'feedpipe_user';
const SESSION_HEADER = 'X-Feedpipe-Session';

const serverInput = document.getElementById('server-url');
const saveServerBtn = document.getElementById('save-server');
const openServerBtn = document.getElementById('open-server');
const injectBtn = document.getElementById('inject-btn');
const urlDisplay = document.getElementById('url-display');
const authStatus = document.getElementById('auth-status');
const statusDiv = document.getElementById('status');

let serverUrl = DEFAULT_SERVER;
let sessionValue = null;

// --- Настройки ---
chrome.storage.sync.get({serverUrl: DEFAULT_SERVER}, function(data) {
    serverUrl = data.serverUrl.replace(/\/+$/, '');
    serverInput.value = serverUrl;
    checkSession();
});

saveServerBtn.addEventListener('click', function() {
    serverUrl = serverInput.value.trim().replace(/\/+$/, '');
    chrome.storage.sync.set({serverUrl: serverUrl}, function() {
        statusDiv.className = 'success';
        statusDiv.textContent = 'Сервер сохранён';
        checkSession();
    });
});

openServerBtn.addEventListener('click', function() {
    chrome.tabs.create({url: serverUrl});
});

// --- Сессия ---
// Сайт уже открыт в браузере и пользователь залогинен — его cookie живёт
// в хранилище браузера. Расширение забирает оттуда подписанную сессию
// (cookies API умеет читать и HttpOnly) и передаёт её серверу заголовком
// X-Feedpipe-Session — cookie cross-origin всё равно не отправилась бы.
function checkSession() {
    try {
        chrome.cookies.get({url: serverUrl, name: COOKIE_NAME}, function(cookie) {
            const err = chrome.runtime.lastError;
            if (err) {
                authStatus.textContent = 'Ошибка: ' + err.message;
                authStatus.className = 'error';
                injectBtn.disabled = true;
                return;
            }
            sessionValue = cookie ? cookie.value : null;
            if (sessionValue) {
                authStatus.textContent = 'SESSION OK';
                authStatus.className = 'success';
                injectBtn.disabled = false;
            } else {
                authStatus.textContent = 'Нужен логин: открой сервер и войди';
                authStatus.className = 'error';
                injectBtn.disabled = true;
            }
        });
    } catch (e) {
        authStatus.textContent = 'Неправильный адрес сервера';
        authStatus.className = 'error';
        injectBtn.disabled = true;
    }
}

// --- Текущая вкладка ---
chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
    urlDisplay.textContent = tabs[0].url;
});

// --- Инжект ---
injectBtn.addEventListener('click', async () => {
    const currentUrl = urlDisplay.textContent;
    injectBtn.disabled = true;
    statusDiv.className = '';
    statusDiv.textContent = 'Отправка...';

    try {
        const response = await fetch(serverUrl + '/api/feeds', {
            method: 'POST',
            headers: {'X-Feedpipe-Session': sessionValue},
            body: new URLSearchParams({url: currentUrl}),
        });

        if (response.ok) {
            statusDiv.className = 'success';
            statusDiv.textContent = 'Фид успешно добавлен!';
            injectBtn.style.display = 'none';
        } else if (response.status === 401) {
            statusDiv.className = 'error';
            statusDiv.textContent = 'Сессия истекла. Открой сервер и войди заново.';
            checkSession();
        } else if (response.status === 409) {
            statusDiv.className = 'error';
            statusDiv.textContent = 'Уже подписан на этот фид.';
            injectBtn.disabled = false;
        } else {
            let message = 'Ошибка сервера.';
            try {
                const data = await response.json();
                if (data.error) message = data.error;
            } catch (e) { /* не JSON — оставляем общее сообщение */ }
            statusDiv.className = 'error';
            statusDiv.textContent = message;
            injectBtn.disabled = false;
        }
    } catch (error) {
        statusDiv.className = 'error';
        statusDiv.textContent = 'Ошибка связи с сервером Feedpipe.';
        injectBtn.disabled = false;
    }
});