const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// URL бэкенда для создания платежей (получаем динамически из query-параметров или используем дефолт)
const urlParams = new URLSearchParams(window.location.search);
const apiBase = urlParams.get('api_url') || 'https://191-44-112-87.sslip.io';
const PAYMENT_API_URL = `${apiBase}/create-payment`;

let currentOrder = null;

// Элементы управления
const btnPay = document.getElementById('btn-pay');
const checkoutModal = document.getElementById('checkout-modal');
const checkoutClose = document.getElementById('checkout-close');
const checkoutSubmit = document.getElementById('checkout-submit');
const checkoutMethod = document.getElementById('checkout-method');
const checkoutCurrency = document.getElementById('checkout-currency');

const mainView = document.getElementById('main-view');
const pendingView = document.getElementById('pending-view');
const btnPendingBack = document.getElementById('btn-pending-back');
const btnFinalPay = document.getElementById('btn-final-pay');

// Открытие модального окна оплаты
function openCheckout() {
    checkoutModal.classList.remove('hidden');
}

function closeCheckout() {
    checkoutModal.classList.add('hidden');
}

btnPay.addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('medium');
    openCheckout();
});

checkoutClose.addEventListener('click', closeCheckout);
checkoutModal.addEventListener('click', (e) => {
    if (e.target === checkoutModal) closeCheckout();
});

// Кнопка «Оплатить» в модалке → переход на pending-view и открытие платежа
checkoutSubmit.addEventListener('click', async () => {
    tg.HapticFeedback.impactOccurred('medium');

    const originalText = checkoutSubmit.innerHTML;
    checkoutSubmit.innerHTML = 'Создание платежа...';
    checkoutSubmit.disabled = true;

    try {
        const telegramId = tg.initDataUnsafe?.user?.id ?? null;
        if (!telegramId) {
            alert('Ошибка: Telegram ID не найден. Откройте приложение внутри Telegram.');
            return;
        }

        const methodValue = checkoutMethod.options[checkoutMethod.selectedIndex].value;
        const methodText = checkoutMethod.options[checkoutMethod.selectedIndex].text;
        const currency = checkoutCurrency.options[checkoutCurrency.selectedIndex].text;

        currentOrder = {
            type: 'sub',
            plan: 'optimal',
            price: '1 ₽',
            methodValue: methodValue,
            methodText: methodText,
            currency: currency
        };

        const response = await fetch(PAYMENT_API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                amount: 1.00,
                description: 'Подписка Оптимальный',
                telegram_id: telegramId,
                method: methodValue
            }),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }

        const { payment_url, payment_id } = await response.json();
        if (!payment_url) {
            throw new Error('Сервер не вернул ссылку на оплату (payment_url)');
        }

        currentOrder.paymentUrl = payment_url;
        currentOrder.paymentId = payment_id;

        // Заполняем pending-view
        document.getElementById('pending-method-text').textContent = methodText;
        document.getElementById('pending-currency-text').textContent = currency;
        document.getElementById('pending-price').textContent = '1 ₽';

        // Смена экрана
        checkoutModal.classList.add('hidden');
        mainView.classList.add('hidden');
        pendingView.classList.remove('hidden');

        // Запускаем поллинг статуса
        startPaymentPolling();

        // Открываем платежную ссылку
        openPaymentLink(payment_url, methodValue);

    } catch (err) {
        console.error('Ошибка создания платежа:', err);
        const errMessage = err.message || "Неизвестная ошибка сети или сервера";
        if (tg.showAlert) {
            tg.showAlert(`Не удалось создать платёж: ${errMessage}`);
        } else {
            alert(`Не удалось создать платёж: ${errMessage}`);
        }
    } finally {
        checkoutSubmit.innerHTML = originalText;
        checkoutSubmit.disabled = false;
    }
});

// Открытие платежной ссылки в зависимости от метода
function openPaymentLink(url, method) {
    if (method === 'stars') {
        tg.openInvoice(url, function (status) {
            if (status === 'paid') {
                tg.close();
            }
        });
    } else if (url.startsWith('https://t.me/') || url.includes('t.me')) {
        tg.openTelegramLink(url);
    } else {
        tg.openLink(url);
    }
}

// Кнопка открыть оплату на pending-экране
btnFinalPay.addEventListener('click', () => {
    if (currentOrder && currentOrder.paymentUrl) {
        tg.HapticFeedback.impactOccurred('light');
        if (btnFinalPay.textContent === 'Открыть чат') {
            tg.close();
        } else {
            openPaymentLink(currentOrder.paymentUrl, currentOrder.methodValue);
        }
    }
});

// Вернуться назад с экрана ожидания
btnPendingBack.addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('light');
    stopPaymentPolling();
    pendingView.classList.add('hidden');
    mainView.classList.remove('hidden');
});

// ── Логика поллинга статуса платежа ──────────────────────────────────────────
let paymentPollingInterval = null;

function stopPaymentPolling() {
    if (paymentPollingInterval) {
        clearInterval(paymentPollingInterval);
        paymentPollingInterval = null;
    }
}

function startPaymentPolling() {
    stopPaymentPolling();

    paymentPollingInterval = setInterval(async () => {
        if (!currentOrder || !currentOrder.paymentId) return;

        try {
            const baseUrl = PAYMENT_API_URL.replace('/create-payment', '');
            const url = `${baseUrl}/check_payment_status?payment_id=${currentOrder.paymentId}`;

            const response = await fetch(url);
            if (!response.ok) return;

            const data = await response.json();

            if (data.status === 'succeeded') {
                stopPaymentPolling();

                // Меняем заголовок экрана
                const titleEl = document.querySelector('#pending-view h1');
                if (titleEl) {
                    titleEl.textContent = '✅ Оплата прошла успешно!';
                }

                // Меняем кнопку на закрытие Mini App
                btnFinalPay.textContent = 'Открыть чат';
            }
        } catch (e) {
            console.error('Ошибка поллинга статуса платежа:', e);
        }
    }, 3000);
}

// Проверка доступности пробного периода
async function checkTrialAvailability() {
    const telegramId = tg.initDataUnsafe?.user?.id ?? null;
    if (!telegramId) return;

    try {
        const baseUrl = PAYMENT_API_URL.replace('/create-payment', '');

        // Сначала проверяем, есть ли уже у пользователя активная подписка
        try {
            const subResponse = await fetch(`${baseUrl}/get-user-subscription?telegram_id=${telegramId}`);
            if (subResponse.ok) {
                const subData = await subResponse.json();
                if (subData.tier && subData.tier !== 'free') {
                    const btnPay = document.getElementById('btn-pay');
                    if (btnPay) {
                        btnPay.disabled = true;
                        btnPay.innerHTML = 'Подписка уже активна';
                        btnPay.style.opacity = '0.5';
                        btnPay.style.pointerEvents = 'none';
                    }
                    const trialBadge = document.getElementById('trial-active-badge');
                    if (trialBadge) {
                        const planNames = { start: 'Старт', optimal: 'Оптимальный', pro: 'Про' };
                        trialBadge.innerText = `У вас уже активна подписка (${planNames[subData.tier] || subData.tier})`;
                        trialBadge.classList.remove('hidden');
                    }
                    return; // Блокируем дальнейшую логику
                }
            }
        } catch (subErr) {
            console.error('Ошибка проверки активной подписки:', subErr);
        }

        const response = await fetch(`${baseUrl}/check-trial-status?telegram_id=${telegramId}`);
        if (response.ok) {
            const data = await response.json();
            if (data.has_used_trial) {
                const btnPay = document.getElementById('btn-pay');
                if (btnPay) {
                    btnPay.disabled = true;
                    btnPay.innerHTML = 'Пробный период уже использован';
                    btnPay.style.opacity = '0.5';
                    btnPay.style.pointerEvents = 'none';
                }
                const header = document.querySelector('header h1');
                if (header) {
                    header.textContent = 'Вы уже использовали пробный период';
                }
                const subtext = document.querySelector('header p');
                if (subtext) {
                    subtext.textContent = 'Оформить пробный период можно только один раз.';
                }

                // Показываем нативное предупреждение и закрываем WebApp
                if (tg.showAlert) {
                    tg.showAlert("Вы уже использовали пробный период.", function() {
                        tg.close();
                    });
                } else {
                    alert("Вы уже использовали пробный период.");
                    tg.close();
                }
            }
        }
    } catch (e) {
        console.error('Ошибка проверки доступности пробного периода:', e);
    }
}

// Запускаем проверку при загрузке
checkTrialAvailability();
