const injectBtn = document.getElementById('inject-btn');
const urlDisplay = document.getElementById('url-display');
const statusDiv = document.getElementById('status');

// ВАЖНО: Замени на IP или домен твоего сервера!
const FEEDPIPE_SERVER = "http://192.168.0.9:8700"; 

// Получаем URL текущей вкладки при открытии попапа
chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
    const currentUrl = tabs[0].url;
    urlDisplay.textContent = currentUrl;
});

injectBtn.addEventListener('click', async () => {
    const currentUrl = urlDisplay.textContent;
    injectBtn.disabled = true;
    statusDiv.className = "";
    statusDiv.textContent = "Отправка...";

    try {
        // Отправляем запрос к твоему API
        const response = await fetch(`${FEEDPIPE_SERVER}/api/feeds`, {
            method: "POST",
            body: new URLSearchParams({ url: currentUrl }),
        });

        if (response.ok) {
            statusDiv.className = "success";
            statusDiv.textContent = "✅ Фид успешно добавлен!";
            injectBtn.style.display = 'none';
        } else if (response.status === 409) {
            statusDiv.className = "error";
            statusDiv.textContent = "⚠️ Уже подписан на этот фид.";
        } else {
            throw new Error("Server error");
        }
    } catch (error) {
        statusDiv.className = "error";
        statusDiv.textContent = "❌ Ошибка связи с сервером Feedpipe.";
        injectBtn.disabled = false;
    }
});