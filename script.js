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
        if (nameEl) nameEl.textContent = 'Savely';
        if (usernameEl) usernameEl.textContent = '@savelyko';
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
    const creditBtns = document.querySelectorAll('.credit-btn');
    creditBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active state from all buttons
            creditBtns.forEach(b => b.classList.remove('active'));
            // Mark this one active
            btn.classList.add('active');
            // Update total price
            const price = btn.dataset.price;
            if (totalPrice) totalPrice.textContent = `${price} ₽`;
            tg.HapticFeedback.selectionChanged();
        });
    });

    // ── Submit order → show confirmation screen ───────────────────────────────
    if (btnSubmitOrder) {
        btnSubmitOrder.addEventListener('click', () => {
            // Read selected package
            const activeBtn = document.querySelector('.credit-btn.active');
            const credits = activeBtn ? activeBtn.dataset.credits : '?';
            const price = activeBtn ? activeBtn.dataset.price : '?';

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
