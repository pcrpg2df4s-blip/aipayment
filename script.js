const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// ── Переключение главных вкладок (Подписка / Токены) ─────────────────────────

const toggleSub = document.getElementById('toggle-sub');
const toggleTokens = document.getElementById('toggle-tokens');
const viewSubscriptions = document.getElementById('view-subscriptions');
const viewTokens = document.getElementById('view-tokens');

const TOGGLE_ACTIVE = ['bg-white', 'text-black', 'shadow-sm', 'rounded-full'];
const TOGGLE_INACTIVE = ['text-gray-400'];

function showSubscriptions() {
    // Активировать кнопку подписки
    toggleSub.classList.add(...TOGGLE_ACTIVE);
    toggleSub.classList.remove(...TOGGLE_INACTIVE);
    // Деактивировать кнопку токенов
    toggleTokens.classList.remove(...TOGGLE_ACTIVE);
    toggleTokens.classList.add(...TOGGLE_INACTIVE);
    // Показать/скрыть views
    viewSubscriptions.classList.remove('hidden');
    viewTokens.classList.add('hidden');
}

function showTokens() {
    // Активировать кнопку токенов
    toggleTokens.classList.add(...TOGGLE_ACTIVE);
    toggleTokens.classList.remove(...TOGGLE_INACTIVE);
    // Деактивировать кнопку подписки
    toggleSub.classList.remove(...TOGGLE_ACTIVE);
    toggleSub.classList.add(...TOGGLE_INACTIVE);
    // Показать/скрыть views
    viewTokens.classList.remove('hidden');
    viewSubscriptions.classList.add('hidden');
}

toggleSub.addEventListener('click', showSubscriptions);
toggleTokens.addEventListener('click', showTokens);

// ── Переключение тарифов подписки ────────────────────────────────────────────

const tabs = [
    { tab: document.getElementById('tab-start'), card: document.getElementById('card-start') },
    { tab: document.getElementById('tab-optimal'), card: document.getElementById('card-optimal') },
    { tab: document.getElementById('tab-pro'), card: document.getElementById('card-pro') },
];

const ACTIVE_TAB = ['text-black', 'border-b-2', 'border-black', 'pb-1'];
const INACTIVE_TAB = ['text-gray-400'];

function switchTab(selectedIndex) {
    tabs.forEach(({ tab, card }, i) => {
        if (i === selectedIndex) {
            tab.classList.remove(...INACTIVE_TAB);
            tab.classList.add(...ACTIVE_TAB);
            card.classList.remove('hidden');
        } else {
            tab.classList.remove(...ACTIVE_TAB);
            tab.classList.add(...INACTIVE_TAB);
            card.classList.add('hidden');
        }
    });
}

tabs.forEach(({ tab }, index) => {
    tab.addEventListener('click', () => switchTab(index));
});

// ── Кнопка оплаты подписки ───────────────────────────────────────────────────

document.getElementById('btn-pay').addEventListener('click', () => {
    tg.HapticFeedback.impactOccurred('medium');
    tg.showAlert("Подключение платежной системы...");
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

    // Синхронизируем слайдер и инпут
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

    // Обновляем отображение
    priceDisplay.textContent = price + '₽';
    amountDisplay.textContent = num + ' токенов';
    bonusDisplay.textContent = 'Всего ' + Math.floor(num * 1.1) + ' токенов';

    // Выделяем активный пресет (если совпадает)
    tokenPresets.forEach(btn => {
        const preset = parseInt(btn.dataset.tokens);
        if (preset === num) {
            btn.classList.add('bg-primary', 'text-white');
            btn.classList.remove('bg-gray-50', 'border', 'border-gray-100', 'text-black');
        } else {
            btn.classList.remove('bg-primary', 'text-white');
            btn.classList.add('bg-gray-50', 'border', 'border-gray-100');
            btn.classList.remove('text-black'); // убираем явный чёрный, если был
        }
    });
}

// Слайдер
tokensSlider.addEventListener('input', (e) => {
    updateTokens(e.target.value);
});

// Поле ввода
tokensInput.addEventListener('input', (e) => {
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
    tg.showAlert("Подключение оплаты...");
});
