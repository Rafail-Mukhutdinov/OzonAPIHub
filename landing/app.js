document.addEventListener('DOMContentLoaded', function() {
    // 1. Установка текущего года в футере
    const yearSpan = document.getElementById('current-year');
    if (yearSpan) {
        yearSpan.textContent = new Date().getFullYear();
    }

    // 2. Проверка авторизации
    const authButtons = document.getElementById('auth-buttons');
    // Flutter shared_preferences web использует префикс 'flutter.'
    const token = localStorage.getItem('flutter.jwt_token');

    if (token && authButtons) {
        authButtons.innerHTML = `
            <a href="/dashboard/" class="btn-primary">Перейти в личный кабинет</a>
        `;
    }

    // 3. Получение версии APK
    const versionSpan = document.getElementById('app-version');
    if (versionSpan) {
        fetch('/static/apps/version.json')
            .then(response => response.json())
            .then(data => {
                if (data && data.version_name) {
                    versionSpan.textContent = data.version_name;
                } else {
                    const tag = document.querySelector('.version-tag');
                    if (tag) tag.style.display = 'none';
                }
            })
            .catch(err => {
                console.error('Ошибка при получении версии:', err);
                const tag = document.querySelector('.version-tag');
                if (tag) tag.style.display = 'none';
            });
    }
});
