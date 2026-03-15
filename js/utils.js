// ── Shared utilities for Family Finance Dashboard ──

window.FF = {

  // Format number as ILS currency
  ils(n) {
    if (n == null) return '—';
    return '₪' + Number(n).toLocaleString('en-IL', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  },

  // Format as USD
  usd(n) {
    if (n == null) return '—';
    return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },

  // Format decimal
  dec(n, places = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: places, maximumFractionDigits: places });
  },

  // Month label like "Jan 2025"
  monthLabel(year, month) {
    const d = new Date(year, month - 1);
    return d.toLocaleDateString('en-IL', { month: 'short', year: 'numeric' });
  },

  // Get current year/month
  currentYM() {
    const d = new Date();
    return { year: d.getFullYear(), month: d.getMonth() + 1 };
  },

  // Toast notifications
  toast(msg, type = 'success') {
    let container = document.querySelector('.toast-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  },

  // Chart defaults
  chartDefaults() {
    Chart.defaults.color = '#9aa0bb';
    Chart.defaults.borderColor = '#2e3550';
    Chart.defaults.font.family = "'DM Mono', monospace";
    Chart.defaults.font.size = 11;
  },

  // API helpers
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async post(url, data) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async put(url, data) {
    const r = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async del(url) {
    const r = await fetch(url, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  // Standard chart colors
  colors: {
    gold: '#c9a84c',
    green: '#4caf88',
    red: '#e05c6a',
    blue: '#5b8df6',
    purple: '#9b7cf8',
    teal: '#4cc9c9',
  },

  // Gradient helper for charts
  gradient(ctx, color, alpha1 = 0.35, alpha2 = 0.0) {
    const g = ctx.createLinearGradient(0, 0, 0, 300);
    const hex = color.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g2 = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    g.addColorStop(0, `rgba(${r},${g2},${b},${alpha1})`);
    g.addColorStop(1, `rgba(${r},${g2},${b},${alpha2})`);
    return g;
  }
};

// Apply chart defaults on load
FF.chartDefaults();
