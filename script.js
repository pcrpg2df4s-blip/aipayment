

const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// УКАЖИТЕ ЗДЕСЬ СВОЙ URL ВАШЕГО БЭКЕНДА (FastAPI) ДЛЯ СОЗДАНИЯ ПЛАТЕЖЕЙ
const PAYMENT_API_URL = 'https://calorie-vision.ru/create-payment';

// ── Текущий заказ ─────────────────────────────────────────────────────────────

let currentOrder = null;

// ── Переключение главных вкладок (Подписка / Токены) ─────────────────────────

const toggleSub = document.getElementById('toggle-sub');
const toggleTokens = document.getElementById('toggle-tokens');
const viewSubscriptions = document.getElementById('view-subscriptions');
const viewTokens = document.getElementById('view-tokens');

const TOGGLE_ACTIVE = ['bg-white', 'text-black', 'shadow-sm', 'rounded-full'];
const TOGGLE_INACTIVE = ['text-gray-400'];

function showSubscriptions() {
    toggleSub.classList.add(...TOGGLE_ACTIVE);
    toggleSub.classList.remove(...TOGGLE_INACTIVE);
    toggleTokens.classList.remove(...TOGGLE_ACTIVE);
    toggleTokens.classList.add(...TOGGLE_INACTIVE);
    viewSubscriptions.classList.remove('hidden');
    viewTokens.classList.add('hidden');
}

function showTokens() {
    toggleTokens.classList.add(...TOGGLE_ACTIVE);
    toggleTokens.classList.remove(...TOGGLE_INACTIVE);
    toggleSub.classList.remove(...TOGGLE_ACTIVE);
    toggleSub.classList.add(...TOGGLE_INACTIVE);
    viewTokens.classList.remove('hidden');
    viewSubscriptions.classList.add('hidden');
}

toggleSub.addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('light');
    showSubscriptions();
});
toggleTokens.addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('light');
    showTokens();
});

// ── Переключение тарифов подписки ────────────────────────────────────────────

let activePlan = 'optimal'; // 'start' | 'optimal' | 'pro'

const tabs = [
    { tab: document.getElementById('tab-start'), card: document.getElementById('card-start'), plan: 'start' },
    { tab: document.getElementById('tab-optimal'), card: document.getElementById('card-optimal'), plan: 'optimal' },
    { tab: document.getElementById('tab-pro'), card: document.getElementById('card-pro'), plan: 'pro' },
];

const ACTIVE_TAB = ['text-black', 'border-b-2', 'border-black', 'pb-1'];
const INACTIVE_TAB = ['text-gray-400'];

function switchTab(selectedIndex) {
    tabs.forEach(({ tab, card, plan }, i) => {
        if (i === selectedIndex) {
            tab.classList.remove(...INACTIVE_TAB);
            tab.classList.add(...ACTIVE_TAB);
            card.classList.remove('hidden');
            activePlan = plan;
        } else {
            tab.classList.remove(...ACTIVE_TAB);
            tab.classList.add(...INACTIVE_TAB);
            card.classList.add('hidden');
        }
    });
}

tabs.forEach(({ tab }, index) => {
    tab.addEventListener('click', () => {
        tg.HapticFeedback.impactOccurred('light');
        switchTab(index);
    });
});

// ── Вспомогательная функция: получить цену активной карточки подписки ─────────

function getActivePlanPrice() {
    const prices = { start: '230₽', optimal: '480₽', pro: '890₽' };
    return prices[activePlan] || '';
}

// ── Модальное окно оплаты ────────────────────────────────────────────────────

const checkoutModal = document.getElementById('checkout-modal');
const checkoutTitle = document.getElementById('checkout-title');
const checkoutClose = document.getElementById('checkout-close');
const checkoutPackage = document.getElementById('checkout-package');
const checkoutPrice = document.getElementById('checkout-price');
const checkoutMethod = document.getElementById('checkout-method');
const checkoutCurrency = document.getElementById('checkout-currency');
const checkoutSubmit = document.getElementById('checkout-submit');

const mainView = document.getElementById('main-view');
const pendingView = document.getElementById('pending-view');

function openCheckout() {
    const scrollY = window.scrollY;
    document.body.style.position = 'fixed';
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = '100%';
    document.body.dataset.scrollY = scrollY;
    checkoutModal.classList.remove('hidden');
}

function closeCheckout() {
    checkoutModal.classList.add('hidden');
    const scrollY = parseInt(document.body.dataset.scrollY || '0');
    document.body.style.position = '';
    document.body.style.top = '';
    document.body.style.width = '';
    window.scrollTo(0, scrollY);
}

// Закрытие по крестику
checkoutClose.addEventListener('click', closeCheckout);

// Закрытие по клику на оверлей (вне карточки)
checkoutModal.addEventListener('click', (e) => {
    if (e.target === checkoutModal) closeCheckout();
});

// ── Кнопка «Оплатить» в модалке → переход на pending-view ──────────────────
checkoutSubmit.addEventListener('click', async () => {
    if (!currentOrder) return;

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

        // 1. Считываем данные из формы
        const methodText = checkoutMethod.options[checkoutMethod.selectedIndex].text;
        const methodValue = checkoutMethod.options[checkoutMethod.selectedIndex].value;
        const currency = checkoutCurrency.options[checkoutCurrency.selectedIndex].text;
        const price = checkoutPrice.innerText;

        // Формируем описание заказа для API
        const planNames = { start: 'Старт', optimal: 'Оптимальный', pro: 'Про' };
        let description = '';
        let amountRaw = 0;

        if (currentOrder.type === 'tokens') {
            description = `Докупка токенов: ${currentOrder.amount}`;
            amountRaw = parseFloat(currentOrder.price);
        } else {
            description = `Подписка ${planNames[currentOrder.plan] || currentOrder.plan}`;
            amountRaw = parseFloat(price.replace(/[^\d.]/g, '')) || 0;
        }

        const response = await fetch(PAYMENT_API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                amount: amountRaw,
                description: description,
                telegram_id: telegramId,
                method: methodValue, // Передаем метод оплаты для бэкенда
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

        // 2. Заполняем pending-view
        const pendingTypeEl = document.getElementById('pending-type');
        const pendingPackageEl = document.getElementById('pending-package');
        const pendingMethodEl = document.getElementById('pending-method-text');
        const pendingCurrencyEl = document.getElementById('pending-currency-text');
        const pendingPriceEl = document.getElementById('pending-price');

        if (currentOrder.type === 'tokens') {
            pendingTypeEl.textContent = 'Докупка токенов';
            pendingPackageEl.textContent = 'Токены: ' + currentOrder.amount;
        } else {
            pendingTypeEl.textContent = 'Подписка';
            pendingPackageEl.textContent = 'Тариф: ' + (planNames[currentOrder.plan] || currentOrder.plan);
        }
        pendingMethodEl.textContent = methodText;
        pendingCurrencyEl.textContent = currency;
        pendingPriceEl.textContent = price;

        // 3. Сохраняем доп. данные в currentOrder
        currentOrder.methodText = methodText;
        currentOrder.methodValue = methodValue;
        currentOrder.currency = currency;

        // 4. Смена экрана
        checkoutModal.classList.add('hidden');
        mainView.classList.add('hidden');
        pendingView.classList.remove('hidden');

        // 5. Разблокируем скролл (теперь полноценная страница)
        const scrollY = parseInt(document.body.dataset.scrollY || '0');
        document.body.style.position = '';
        document.body.style.top = '';
        document.body.style.width = '';
        window.scrollTo(0, scrollY);
        document.body.classList.remove('overflow-hidden');
        window.scrollTo(0, 0);

        // Запускаем поллинг статуса
        startPaymentPolling();

        // 6. ОДНОВРЕМЕННО открываем ссылку
        if (methodValue === 'stars') {
            tg.openInvoice(payment_url, function (status) {
                if (status === 'paid') {
                    tg.close();
                }
            });
        } else if (payment_url.startsWith('https://t.me/') || payment_url.includes('t.me')) {
            tg.openTelegramLink(payment_url);
        } else {
            tg.openLink(payment_url);
        }
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

// ── Логика поллинга ──────────────────────────────────────────────────────────
let paymentPollingInterval = null;

function stopPaymentPolling() {
    if (paymentPollingInterval) {
        clearInterval(paymentPollingInterval);
        paymentPollingInterval = null;
    }
}

function startPaymentPolling() {
    stopPaymentPolling();

    // Запускаем интервал каждые 3 секунды
    paymentPollingInterval = setInterval(async () => {
        if (!currentOrder || !currentOrder.paymentId) return;

        try {
            // URL без /create-payment
            const baseUrl = PAYMENT_API_URL.replace('/create-payment', '');
            const url = `${baseUrl}/check_payment_status?payment_id=${currentOrder.paymentId}`;

            const response = await fetch(url);
            if (!response.ok) return;

            const data = await response.json();

            if (data.status === 'succeeded') {
                stopPaymentPolling();

                // Меняем заголовок
                const titleEl = document.querySelector('#pending-view h1');
                if (titleEl) {
                    titleEl.textContent = '✅ Оплата прошла успешно!';
                }

                // Меняем кнопку
                const finalPayBtn = document.getElementById('btn-final-pay');
                if (finalPayBtn) {
                    finalPayBtn.textContent = 'Открыть чат';
                    // Меняем обработчик на закрытие Mini App (пересоздаем кнопку, чтобы удалить старый onclick)
                    const newFinalPayBtn = finalPayBtn.cloneNode(true);
                    finalPayBtn.parentNode.replaceChild(newFinalPayBtn, finalPayBtn);

                    newFinalPayBtn.addEventListener('click', () => {
                        tg.close();
                    });
                }

                // Скрываем кнопку "Вернуться"
                const backBtn = document.getElementById('btn-pending-back');
                if (backBtn) backBtn.classList.add('hidden');

            } else if (data.status === 'canceled') {
                stopPaymentPolling();
                const titleEl = document.querySelector('#pending-view h1');
                if (titleEl) {
                    titleEl.textContent = '❌ Оплата отменена';
                }
            }
        } catch (err) {
            console.error('Ошибка поллинга платежа:', err);
        }
    }, 3000);
}

// ── Кнопка «Вернуться» в pending-view ────────────────────────────────────────
document.getElementById('btn-pending-back').addEventListener('click', () => {
    stopPaymentPolling();
    pendingView.classList.add('hidden');
    mainView.classList.remove('hidden');
    // Восстанавливаем модалку со скролл-локом
    openCheckout();
});

// ── Кнопка «Открыть оплату» в pending-view ───────────────────────────────────
document.getElementById('btn-final-pay').addEventListener('click', () => {
    if (!currentOrder || !currentOrder.paymentUrl) return;

    tg.HapticFeedback.impactOccurred('medium');
    if (currentOrder.methodValue === 'stars') {
        tg.openInvoice(currentOrder.paymentUrl, function (status) {
            if (status === 'paid') {
                tg.close();
            }
        });
    } else if (currentOrder.paymentUrl.startsWith('https://t.me/') || currentOrder.paymentUrl.includes('t.me')) {
        tg.openTelegramLink(currentOrder.paymentUrl);
    } else {
        tg.openLink(currentOrder.paymentUrl);
    }
});

// ── Кнопка оплаты подписки ───────────────────────────────────────────────────

document.getElementById('btn-pay').addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('medium');

    const planNames = { start: 'Старт', optimal: 'Оптимальный', pro: 'Про' };
    const planPrice = getActivePlanPrice();

    checkoutTitle.innerHTML = 'Покупка<br/>подписки';
    checkoutPackage.innerText = 'Тариф: ' + (planNames[activePlan] || activePlan);
    checkoutPrice.innerText = planPrice;

    currentOrder = { type: 'sub', plan: activePlan };

    openCheckout();
});

// ── Калькулятор токенов ──────────────────────────────────────────────────────

const tokensSlider = document.getElementById('tokens-slider');
const tokensInput = document.getElementById('tokens-input');
const priceDisplay = document.getElementById('price-display');
const amountDisplay = document.getElementById('amount-display');
const bonusDisplay = document.getElementById('bonus-display');
const tokenPresets = document.querySelectorAll('.token-preset');

function updateTokens(value) {
    const num = Math.max(100, Math.min(5000, parseInt(value) || 100));

    tokensSlider.value = num;
    tokensInput.value = num;

    // Прогрессивная цена: чем больше токенов — тем дешевле
    let price;
    if (num <= 500) {
        price = num * 1;
    } else if (num <= 1000) {
        price = num * 0.95;
    } else if (num <= 2000) {
        price = num * 0.9;
    } else {
        price = num * 0.8;
    }
    price = Math.round(price);

    priceDisplay.textContent = price + '₽';
    amountDisplay.textContent = num + ' токенов';
    bonusDisplay.textContent = 'Всего ' + Math.floor(num * 1.1) + ' токенов';

    tokenPresets.forEach(btn => {
        const preset = parseInt(btn.dataset.tokens);
        if (preset === num) {
            btn.classList.add('bg-primary', 'text-white');
            btn.classList.remove('bg-gray-50', 'border', 'border-gray-100', 'text-black');
        } else {
            btn.classList.remove('bg-primary', 'text-white');
            btn.classList.add('bg-gray-50', 'border', 'border-gray-100');
            btn.classList.remove('text-black');
        }
    });
}

// Слайдер
tokensSlider.addEventListener('input', (e) => {
    updateTokens(e.target.value);
});

// Поле ввода — при наборе только синхронизируем слайдер
tokensInput.addEventListener('input', (e) => {
    const raw = parseInt(e.target.value) || 0;
    const clamped = Math.max(100, Math.min(5000, raw));
    tokensSlider.value = clamped;
});

// При потере фокуса применяем минимум 100
tokensInput.addEventListener('blur', (e) => {
    updateTokens(e.target.value);
});

// Кнопки-пресеты
tokenPresets.forEach(btn => {
    btn.addEventListener('click', () => {
        updateTokens(parseInt(btn.dataset.tokens));
    });
});

// Инициализация (500 токенов по умолчанию)
updateTokens(500);

// ── Кнопка покупки токенов ───────────────────────────────────────────────────

document.getElementById('btn-pay-tokens').addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('medium');

    const amount = tokensInput.value;
    const price = priceDisplay.textContent.replace('₽', '').trim();

    checkoutTitle.innerHTML = 'Покупка дополнительных<br/>токенов';
    checkoutPackage.innerText = 'Токены: ' + amount;
    checkoutPrice.innerText = price + ' ₽';

    currentOrder = { type: 'tokens', amount: amount, price: price };

    openCheckout();
});
