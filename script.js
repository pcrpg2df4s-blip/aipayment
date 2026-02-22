// ─── Telegram Web App SDK ────────────────────────────────────────────────────
const tg = window.Telegram.WebApp;

// Expand to full screen immediately
tg.expand();

// ─── User initialisation ─────────────────────────────────────────────────────
/**
 * Pulls user data from Telegram's initDataUnsafe and populates the UI.
 * Falls back to placeholder values when running in a regular browser.
 */
function initUser() {
    const user = tg.initDataUnsafe?.user;

    const nameEl = document.getElementById('user-name');
    const usernameEl = document.getElementById('user-username');
    const avatarEl = document.getElementById('user-avatar');

    if (user) {
        // Build display name from first + last name
        const fullName = [user.first_name, user.last_name]
            .filter(Boolean)
            .join(' ');

        if (nameEl) nameEl.textContent = fullName || 'Пользователь';
        if (usernameEl) usernameEl.textContent = user.username ? `@${user.username}` : '';
        if (avatarEl && user.photo_url) {
            avatarEl.src = user.photo_url;
            avatarEl.alt = fullName || 'Avatar';
        }
    } else {
        // Browser fallback – keep design placeholders
        if (nameEl) nameEl.textContent = 'Гость';
        if (usernameEl) usernameEl.textContent = '@гость';
        // Avatar keeps its default src from HTML
    }
}

// ─── Button handlers ──────────────────────────────────────────────────────────
function initButtons() {
    const btnBuyCredits = document.getElementById('btn-buy-credits');
    const btnBuyPro = document.getElementById('btn-buy-pro');
    const modal = document.getElementById('buy-credits-modal');
    const closeBtn = document.getElementById('close-modal-btn');
    const backdrop = document.getElementById('modal-backdrop');
    const totalPrice = document.getElementById('total-price');

    const confirmationScreen = document.getElementById('payment-confirmation-screen');
    const btnSubmitOrder = document.getElementById('btn-submit-order');
    const btnGoBack = document.getElementById('btn-go-back');
    const btnOpenGateway = document.getElementById('btn-open-gateway');

    // Confirmation screen fields
    const confirmCredits = document.getElementById('confirm-credits');
    const confirmMethod = document.getElementById('confirm-method');
    const confirmCurrency = document.getElementById('confirm-currency');
    const confirmEmail = document.getElementById('confirm-email');
    const confirmTotal = document.getElementById('confirm-total');

    // Modal form fields
    const inputEmail = document.getElementById('input-email');
    const selectMethod = document.getElementById('select-method');
    const selectCurrency = document.getElementById('select-currency');

    // ── Helpers ──────────────────────────────────────────────────────────────
    function openModal() {
        if (modal) modal.classList.remove('hidden');
        tg.HapticFeedback.impactOccurred('medium');
    }

    function closeModal() {
        if (modal) modal.classList.add('hidden');
    }

    // ── Open modal ───────────────────────────────────────────────────────────
    if (btnBuyCredits) {
        btnBuyCredits.addEventListener('click', openModal);
    }

    // ── Close modal ──────────────────────────────────────────────────────────
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (backdrop) backdrop.addEventListener('click', closeModal);

    // ── Credit package selection ─────────────────────────────────────────────
    const INACTIVE_CN = "flex items-center justify-center py-3 bg-white dark:bg-zinc-900 text-black dark:text-white border border-black dark:border-zinc-700 rounded-xl font-semibold hover:bg-gray-50 dark:hover:bg-zinc-800 transition-colors";
    const ACTIVE_CN = "flex items-center justify-center py-3 bg-black text-white border border-black rounded-xl font-semibold shadow-md";

    const creditButtons = document.querySelectorAll('.credit-btn');
    let selectedCredits = null;

    const prices = {
        '100': '100 ₽',
        '250': '250 ₽',
        '500': '500 ₽',
        '1000': '1000 ₽'
    };

    creditButtons.forEach(btn => {
        btn.addEventListener('click', function () {
            // 1. СБРОС: все кнопки → неактивное состояние
            creditButtons.forEach(b => { b.className = INACTIVE_CN; });

            // 2. АКТИВАЦИЯ: нажатая кнопка → активное состояние
            this.className = ACTIVE_CN;

            // 3. Сохраняем выбор и обновляем сумму
            selectedCredits = this.dataset.credits ?? this.innerText.trim();
            const creditsKey = this.innerText.trim();
            if (totalPrice && prices[creditsKey]) {
                totalPrice.innerText = prices[creditsKey];
            }

            tg.HapticFeedback.selectionChanged();
        });
    });

    // ── Submit order → show confirmation screen ───────────────────────────────
    if (btnSubmitOrder) {
        btnSubmitOrder.addEventListener('click', () => {
            // Read selected package (active button has bg-black in its className)
            const activeBtn = [...creditButtons].find(b => b.classList.contains('bg-black'));
            const credits = selectedCredits ?? (activeBtn ? activeBtn.innerText.trim() : '?');
            const price = activeBtn ? (prices[activeBtn.innerText.trim()] ?? '?') : '?';

            // Read form fields
            const email = inputEmail ? inputEmail.value.trim() : '';
            const method = selectMethod ? selectMethod.value : '';
            const currency = selectCurrency ? selectCurrency.value : '';

            // Currency symbol map
            const currencySymbol = { RUB: '₽', USD: '$', EUR: '€' };
            const symbol = currencySymbol[currency] || currency;

            // Populate confirmation screen
            if (confirmCredits) confirmCredits.textContent = `${credits} кредитов`;
            if (confirmMethod) confirmMethod.textContent = method;
            if (confirmCurrency) confirmCurrency.textContent = currency;
            if (confirmEmail) confirmEmail.textContent = email || '—';
            if (confirmTotal) confirmTotal.textContent = `${price} ${symbol}`;

            // Switch screens
            closeModal();
            if (confirmationScreen) confirmationScreen.classList.remove('hidden');

            tg.HapticFeedback.impactOccurred('medium');
        });
    }

    // ── Go back → hide confirmation, reopen modal ─────────────────────────────
    if (btnGoBack) {
        btnGoBack.addEventListener('click', () => {
            if (confirmationScreen) confirmationScreen.classList.add('hidden');
            openModal();
        });
    }

    // ── Open gateway (placeholder) ────────────────────────────────────────────
    if (btnOpenGateway) {
        btnOpenGateway.addEventListener('click', () => {
            tg.showAlert('Генерация ссылки на оплату...');
        });
    }

    // ── Pro plan button ───────────────────────────────────────────────────────
    if (btnBuyPro) {
        btnBuyPro.addEventListener('click', () => {
            tg.HapticFeedback.impactOccurred('medium');
            tg.showAlert('Функция оплаты в разработке!');
        });
    }
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initUser();
    initButtons();
});
