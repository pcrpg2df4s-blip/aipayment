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
    const paymentScreen = document.getElementById('payment-screen');
    const btnClosePayment = document.getElementById('btn-close-payment');
    const btnSubmitPayment = document.getElementById('btn-submit-payment');

    // ── Open payment screen ───────────────────────────────────────────────────
    if (btnBuyCredits) {
        btnBuyCredits.addEventListener('click', () => {
            if (paymentScreen) paymentScreen.classList.remove('hidden');
            tg.HapticFeedback.impactOccurred('medium');
        });
    }

    // ── Close payment screen (back to profile) ───────────────────────────────
    if (btnClosePayment) {
        btnClosePayment.addEventListener('click', () => {
            if (paymentScreen) paymentScreen.classList.add('hidden');
            tg.HapticFeedback.impactOccurred('light');
        });
    }

    // ── Pay button (placeholder) ─────────────────────────────────────────────
    if (btnSubmitPayment) {
        btnSubmitPayment.addEventListener('click', () => {
            tg.showAlert('Подключение платежного шлюза...');
            tg.HapticFeedback.impactOccurred('medium');
        });
    }
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initUser();
    initButtons();
});
