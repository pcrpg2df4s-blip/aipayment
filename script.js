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
