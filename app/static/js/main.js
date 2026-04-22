// Theme
const savedTheme = localStorage.getItem('rbl-theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);
updateThemeBtn(savedTheme);

function toggleTheme() {
  const cur  = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('rbl-theme', next);
  updateThemeBtn(next);
  setTimeout(() => location.reload(), 100);
}
function updateThemeBtn(t) {
  const b = document.getElementById('themeBtn');
  if (b) b.textContent = t === 'dark' ? '🌙' : '☀️';
}

// Sidebar
function toggleSidebar() {
  const s = document.getElementById('sidebar');
  const m = document.querySelector('.main-wrapper');
  if (window.innerWidth <= 768) { s.classList.toggle('open'); }
  else { s.classList.toggle('collapsed'); if(m) m.classList.toggle('full'); }
}

// Toast
let toastTimer;
function showToast(msg, type = 'success') {
  const t    = document.getElementById('toast');
  const icon = document.getElementById('toastIcon');
  const text = document.getElementById('toastText');
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
  if (icon) icon.textContent = icons[type] || 'ℹ️';
  if (text) text.textContent = msg;
  if (t) { t.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 3200); }
}

// Form stepper
let currentStep = 1;
const totalSteps = 5;

function goStep(n) {
  if (n > currentStep && !validateStep(currentStep)) return;
  if (n === totalSteps) populateReview();
  currentStep = n;
  renderStepper();
}
function renderStepper() {
  for (let i = 1; i <= totalSteps; i++) {
    const sc = document.getElementById('step-' + i);
    const fc = document.getElementById('form-step-' + i);
    if (sc) sc.className = 'step' + (i < currentStep ? ' done' : i === currentStep ? ' active' : '');
    if (fc) fc.classList.toggle('hidden', i !== currentStep);
  }
}
function validateStep(n) {
  const card = document.getElementById('form-step-' + n);
  if (!card) return true;
  let ok = true;
  card.querySelectorAll('[required]').forEach(el => {
    if (!el.value.trim()) { el.style.borderColor = 'var(--rbl-red)'; el.addEventListener('input', () => el.style.borderColor = '', { once: true }); ok = false; }
  });
  if (!ok) showToast('Please fill all required fields', 'error');
  return ok;
}

// Budget calculations
function calcDiffs() {
  const a = parseFloat(document.getElementById('budgetA')?.value) || 0;
  const b = parseFloat(document.getElementById('budgetB')?.value) || null;
  const c = parseFloat(document.getElementById('budgetC')?.value) || 0;
  const hasA = document.getElementById('budgetA')?.value !== '';
  if (b !== null) setCalc('calcAB', a - b, hasA);
  else { const el = document.getElementById('calcAB'); if(el){el.textContent='—';el.style.color='var(--text-muted)';} }
  if (b !== null) setCalc('calcCB', c - b, hasA);
  else { const el = document.getElementById('calcCB'); if(el){el.textContent='—';el.style.color='var(--text-muted)';} }
  setCalc('calcCA', c - a, hasA);
}
function setCalc(id, val, hasInput) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!hasInput) { el.textContent = '—'; el.style.color = 'var(--text-muted)'; return; }
  el.textContent = (val >= 0 ? '+ ' : '− ') + '₹' + Math.abs(val).toLocaleString('en-IN', {maximumFractionDigits:2});
  el.style.color = val >= 0 ? 'var(--success)' : 'var(--rbl-light-red)';
}

// Review populate
function populateReview() {
  const getText = id => { const e=document.getElementById(id); return e?.options?.[e.selectedIndex]?.text || e?.value || '—'; };
  const getVal  = id => document.getElementById(id)?.value || '—';
  const fmt     = v => v && v !== '—' ? '₹' + parseFloat(v).toLocaleString('en-IN') : '—';
  setRev('rev-oldnew',   getText('oldNew'));
  setRev('rev-business', getText('businessSelect'));
  setRev('rev-costcode', document.getElementById('costCodeDisplay')?.textContent || '—');
  setRev('rev-ithead',   document.getElementById('itHeadDisplay')?.textContent || '—');
  setRev('rev-type',     getText('expenseSubType'));
  setRev('rev-app',      getVal('applicationPlatform'));
  setRev('rev-vendor',   getVal('vendorName'));
  setRev('rev-desc',     getVal('shortDescription'));
  setRev('rev-a', fmt(getVal('budgetA')));
  setRev('rev-b', fmt(getVal('budgetB')));
  setRev('rev-c', fmt(getVal('budgetC')));
  const a=parseFloat(getVal('budgetA'))||0, b=parseFloat(getVal('budgetB'))||null;
  if (b !== null) { const diff=a-b; const el=document.getElementById('rev-ab'); if(el){el.textContent=(diff>=0?'+ ':'− ')+'₹'+Math.abs(diff).toLocaleString('en-IN');el.style.color=diff>=0?'var(--success)':'var(--rbl-light-red)';} }
}
function setRev(id, val) { const e=document.getElementById(id); if(e) e.textContent=val; }

// Conditional fields
function togglePrevKey() {
  const v  = document.getElementById('oldNew')?.value;
  const el = document.getElementById('prevKeyField');
  if (!el) return;
  const show = v === 'Old' || v === 'Old But Incremental';
  el.classList.toggle('hidden', !show);
  const inp = el.querySelector('input');
  if (inp) inp.required = show;
}

// Business → Cost Code map
const COST_CODES = {
  "Operation Technology" : 3709, "RISK Technology": 3708,
  "Technology infra": 3701, "Technology operations": 3717,
  "Technology others": 3722, "Technology shared DWH": 3716, "Treasury": 3714,
};
function autoFillCostCode() {
  const sel = document.getElementById('businessSelect');
  if (!sel) return;
  const v   = sel.options[sel.selectedIndex]?.text || sel.value;
  const el  = document.getElementById('costCodeDisplay');
  const hid = document.getElementById('costCodeHidden');
  const code = COST_CODES[v];
  if (el)  el.textContent = code || 'Select a Business Unit first';
  if (hid) hid.value = code || '';
}

// Confirm dialogs
function confirmAction(msg, formId) {
  if (confirm(msg)) document.getElementById(formId)?.submit();
}
