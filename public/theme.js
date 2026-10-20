/* Applies the saved colour theme before the page paints (kept tiny on purpose). */
try { var t = localStorage.getItem('semlab-theme'); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch (e) {}
