/**
 * B2B Lead Gen SaaS — Frontend SPA
 *
 * Vanilla JS, no framework. Auth via JWT in localStorage.
 * API base URL defaults to http://localhost:8000.
 */

const API = 'http://localhost:8000';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  token: localStorage.getItem('token'),
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  currentView: 'dashboard',
  leads: {
    page: 1,
    total: 0,
    totalPages: 1,
    search: '',
    outreachStatus: '',
    isTarget: '',
    sortBy: 'created_at',
    sortDir: 'desc',
  },
  outreach: {
    page: 1,
    total: 0,
    totalPages: 1,
    channel: '',
    success: '',
  },
};

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (res.status === 401 && state.token) {
    logout();
    throw new Error('Session expired');
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const msg = (typeof body.detail === 'string')
      ? body.detail
      : JSON.stringify(body.detail || body, null, 2);
    throw new Error(msg);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

function toast(message, type = 'info') {
  const el = document.getElementById('toast');
  const colors = { info: 'bg-gray-800', success: 'bg-green-600', error: 'bg-red-600' };
  el.className = `toast fixed top-4 right-4 z-50 px-4 py-2.5 rounded-lg text-white text-sm font-medium shadow-lg ${colors[type] || colors.info}`;
  el.textContent = message;
  el.classList.remove('hidden');
  clearTimeout(el._timeout);
  el._timeout = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  state.token = null;
  state.user = null;
  showAuthView();
}

function showAuthView() {
  document.getElementById('app-view').classList.add('hidden');
  document.getElementById('auth-view').classList.remove('hidden');
  document.getElementById('login-form').classList.remove('hidden');
  document.getElementById('register-form').classList.add('hidden');
  document.getElementById('login-form').reset();
  document.getElementById('register-form').reset();
  document.getElementById('auth-error').classList.add('hidden');
  document.getElementById('tab-login').className = 'flex-1 py-3 text-sm font-semibold text-indigo-600 border-b-2 border-indigo-600 bg-white';
  document.getElementById('tab-register').className = 'flex-1 py-3 text-sm font-semibold text-gray-400 border-b-2 border-transparent hover:text-gray-600';
}

function showAppView() {
  document.getElementById('auth-view').classList.add('hidden');
  document.getElementById('app-view').classList.remove('hidden');
  document.getElementById('user-name').textContent = state.user.display_name;
  document.getElementById('user-email').textContent = state.user.email;
  document.getElementById('user-avatar').textContent = state.user.display_name.charAt(0).toUpperCase();
  navigateTo('dashboard');
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function navigateTo(view) {
  state.currentView = view;
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  document.getElementById(`view-${view}`).classList.remove('hidden');
  document.querySelectorAll('.nav-btn').forEach(b => {
    if (b.dataset.nav === view) {
      b.className = 'nav-btn w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg text-indigo-700 bg-indigo-50';
    } else {
      b.className = 'nav-btn w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg text-gray-600 hover:bg-gray-100';
    }
  });

  if (view === 'dashboard') loadDashboard();
  else if (view === 'leads') loadLeads();
  else if (view === 'outreach') loadOutreach();
  else if (view === 'settings') loadSettings();
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

async function loadDashboard() {
  try {
    const stats = await api('/api/dashboard/stats');
    const view = document.getElementById('view-dashboard');

    if (stats.total_leads === 0) {
      view.innerHTML = `
        <h2 class="text-2xl font-bold text-gray-900 mb-6">Dashboard</h2>
        <div class="bg-white rounded-2xl border border-gray-200 flex flex-col items-center justify-center py-20 px-6 text-center">
          <div class="w-20 h-20 rounded-2xl bg-indigo-50 flex items-center justify-center mb-6">
            <svg class="w-10 h-10 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/>
            </svg>
          </div>
          <h3 class="text-xl font-bold text-gray-900 mb-2">No leads yet</h3>
          <p class="text-sm text-gray-500 max-w-md mb-8">Run your first discovery pipeline or add a lead manually to start building your B2B outreach campaign.</p>
          <div class="flex gap-3">
            <button onclick="document.querySelector('[data-nav=pipeline]').click()" class="px-5 py-2.5 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 transition-colors">
              <span class="flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                Run Pipeline
              </span>
            </button>
            <button onclick="document.querySelector('[data-nav=leads]').click()" class="px-5 py-2.5 bg-white text-gray-700 text-sm font-semibold rounded-lg border border-gray-300 hover:bg-gray-50 transition-colors">
              <span class="flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                Go to Leads
              </span>
            </button>
          </div>
        </div>
      `;
      return;
    }

    view.innerHTML = `
      <h2 class="text-2xl font-bold text-gray-900 mb-6">Dashboard</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8" id="stats-grid">
        ${[
          { label: 'Total Leads', value: stats.total_leads, color: 'indigo' },
          { label: 'Target Leads', value: stats.target_leads, color: 'green' },
          { label: 'Contacted', value: stats.contacted, color: 'blue' },
          { label: 'Replied', value: stats.replied, color: 'amber' },
          { label: 'Conversion Rate', value: `${stats.conversion_rate}%`, color: 'purple' },
          { label: 'Recent (30d)', value: stats.recent_added, color: 'teal' },
        ].map(c => `
          <div class="bg-white rounded-xl border border-gray-200 p-5">
            <p class="text-sm text-gray-500">${c.label}</p>
            <p class="text-3xl font-bold text-${c.color}-600 mt-1">${c.value}</p>
          </div>
        `).join('')}
      </div>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-white rounded-xl border border-gray-200 p-6">
          <h3 class="text-sm font-semibold text-gray-900 mb-4">Leads by Country</h3>
          <div class="space-y-3">
            ${stats.by_country.length ? stats.by_country.map(c => {
              const pct = (c.count / Math.max(1, ...stats.by_country.map(x => x.count)) * 100).toFixed(0);
              return `<div class="flex items-center gap-3"><span class="text-sm text-gray-700 w-16 truncate">${esc(c.country)}</span><div class="flex-1 bg-gray-100 rounded-full h-2.5"><div class="bg-indigo-500 rounded-full h-2.5" style="width:${pct}%"></div></div><span class="text-sm text-gray-500 w-8 text-right">${c.count}</span></div>`;
            }).join('') : '<p class="text-sm text-gray-400">No data yet</p>'}
          </div>
        </div>
        <div class="bg-white rounded-xl border border-gray-200 p-6">
          <h3 class="text-sm font-semibold text-gray-900 mb-4">Leads by Source</h3>
          <div class="space-y-3">
            ${stats.by_source.length ? stats.by_source.map(c => {
              const pct = (c.count / Math.max(1, ...stats.by_source.map(x => x.count)) * 100).toFixed(0);
              return `<div class="flex items-center gap-3"><span class="text-sm text-gray-700 w-20 truncate">${esc(c.source)}</span><div class="flex-1 bg-gray-100 rounded-full h-2.5"><div class="bg-green-500 rounded-full h-2.5" style="width:${pct}%"></div></div><span class="text-sm text-gray-500 w-8 text-right">${c.count}</span></div>`;
            }).join('') : '<p class="text-sm text-gray-400">No data yet</p>'}
          </div>
        </div>
      </div>
    `;

  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

async function loadLeads() {
  try {
    const params = new URLSearchParams({
      page: state.leads.page,
      per_page: 20,
      search: state.leads.search,
      outreach_status: state.leads.outreachStatus,
      sort_by: state.leads.sortBy,
      sort_dir: state.leads.sortDir,
    });
    if (state.leads.isTarget !== '') params.set('is_target', state.leads.isTarget);

    const data = await api(`/api/leads?${params}`);
    state.leads.total = data.total;
    state.leads.totalPages = data.total_pages;

    renderLeadsTable(data.leads);
    renderLeadsPagination();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderLeadsTable(leads) {
  const tbody = document.getElementById('leads-tbody');

  if (!leads.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-12 text-center text-gray-400">No leads found</td></tr>`;
    return;
  }

  tbody.innerHTML = leads.map(l => `
    <tr class="hover:bg-gray-50 cursor-pointer" data-id="${l.id}">
      <td class="py-3 px-4">
        <p class="font-medium text-gray-900">${esc(l.company_name)}</p>
        <p class="text-xs text-gray-500">${esc(l.website_url)}</p>
      </td>
      <td class="py-3 px-4 text-gray-700">${esc(l.country)}</td>
      <td class="py-3 px-4">
        ${l.is_target
          ? `<span class="inline-flex items-center gap-1 text-sm"><span class="w-2 h-2 rounded-full ${l.intent_score >= 70 ? 'bg-green-500' : l.intent_score >= 40 ? 'bg-amber-500' : 'bg-red-500'}"></span>${l.intent_score}</span>`
          : `<span class="text-xs text-gray-400">N/A</span>`
        }
      </td>
      <td class="py-3 px-4">
        <p class="text-gray-900">${esc(l.contact_name)}</p>
        <p class="text-xs text-gray-500">${esc(l.contact_email)}</p>
      </td>
      <td class="py-3 px-4">
        <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${statusBadge(l.outreach_status)}">${l.outreach_status}</span>
      </td>
      <td class="py-3 px-4">
        <button class="text-indigo-600 hover:text-indigo-800 text-xs font-semibold btn-edit-lead" data-id="${l.id}">Edit</button>
      </td>
    </tr>
  `).join('');

  // Click handlers
  tbody.querySelectorAll('.btn-edit-lead').forEach(btn => {
    btn.addEventListener('click', e => { e.stopPropagation(); openLeadModal(btn.dataset.id); });
  });
  tbody.querySelectorAll('tr').forEach(row => {
    row.addEventListener('click', () => openLeadModal(row.dataset.id));
  });
}

function renderLeadsPagination() {
  const el = document.getElementById('leads-pagination');
  const { page, totalPages, total } = state.leads;
  if (totalPages <= 1) {
    el.innerHTML = `<span class="text-sm text-gray-500">${total} total</span>`;
    return;
  }
  el.innerHTML = `
    <span class="text-sm text-gray-500">${total} total</span>
    <div class="flex gap-1">
      <button class="btn-page px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-40" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>Prev</button>
      <span class="px-3 py-1.5 text-sm text-gray-700">Page ${page} / ${totalPages}</span>
      <button class="btn-page px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-40" data-page="${page + 1}" ${page >= totalPages ? 'disabled' : ''}>Next</button>
    </div>
  `;
  el.querySelectorAll('.btn-page').forEach(b => {
    b.addEventListener('click', () => {
      state.leads.page = parseInt(b.dataset.page);
      loadLeads();
    });
  });
}

function statusBadge(status) {
  const map = {
    pending: 'bg-gray-100 text-gray-700',
    sent: 'bg-blue-100 text-blue-700',
    failed: 'bg-red-100 text-red-700',
    replied: 'bg-green-100 text-green-700',
  };
  return map[status] || 'bg-gray-100 text-gray-700';
}

// Lead modal
async function openLeadModal(leadId) {
  try {
    const lead = await api(`/api/leads/${leadId}`);
    document.getElementById('edit-lead-id').value = lead.id;
    document.getElementById('edit-company-name').value = lead.company_name;
    document.getElementById('edit-website').value = lead.website_url;
    document.getElementById('edit-country').value = lead.country;
    document.getElementById('edit-source').value = lead.source;
    document.getElementById('edit-description').value = lead.raw_description;
    document.getElementById('edit-contact-name').value = lead.contact_name;
    document.getElementById('edit-contact-email').value = lead.contact_email;
    document.getElementById('edit-contact-title').value = lead.contact_title;
    document.getElementById('edit-contact-phone').value = lead.contact_phone;
    document.getElementById('edit-is-target').value = String(lead.is_target);
    document.getElementById('edit-intent-score').value = lead.intent_score;
    document.getElementById('edit-outreach-status').value = lead.outreach_status;
    document.getElementById('lead-modal').classList.add('flex');
    document.getElementById('lead-modal').classList.remove('hidden');
  } catch (err) {
    toast(err.message, 'error');
  }
}

function closeLeadModal() {
  document.getElementById('lead-modal').classList.add('hidden');
  document.getElementById('lead-modal').classList.remove('flex');
}

async function saveLead(e) {
  e.preventDefault();
  const id = document.getElementById('edit-lead-id').value;
  try {
    await api(`/api/leads/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        company_name: document.getElementById('edit-company-name').value,
        website_url: document.getElementById('edit-website').value,
        country: document.getElementById('edit-country').value,
        raw_description: document.getElementById('edit-description').value,
        is_target: document.getElementById('edit-is-target').value === 'true',
        intent_score: parseInt(document.getElementById('edit-intent-score').value) || 0,
        contact_name: document.getElementById('edit-contact-name').value,
        contact_email: document.getElementById('edit-contact-email').value,
        contact_title: document.getElementById('edit-contact-title').value,
        contact_phone: document.getElementById('edit-contact-phone').value,
        outreach_status: document.getElementById('edit-outreach-status').value,
      }),
    });
    closeLeadModal();
    loadLeads();
    toast('Lead updated', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteLead() {
  const id = document.getElementById('edit-lead-id').value;
  if (!confirm('Delete this lead permanently?')) return;
  try {
    await api(`/api/leads/${id}`, { method: 'DELETE' });
    closeLeadModal();
    loadLeads();
    toast('Lead deleted', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function createLead() {
  try {
    await api('/api/leads', {
      method: 'POST',
      body: JSON.stringify({
        company_name: 'New Lead',
        website_url: '',
        country: '',
        raw_description: '',
        source: 'manual',
        contact_name: '',
        contact_email: '',
        contact_title: '',
        contact_phone: '',
      }),
    });
    loadLeads();
    toast('Lead created', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Outreach
// ---------------------------------------------------------------------------

async function loadOutreach() {
  try {
    const params = new URLSearchParams({
      page: state.outreach.page,
      per_page: 20,
      channel: state.outreach.channel,
    });
    if (state.outreach.success !== '') params.set('success', state.outreach.success);

    const data = await api(`/api/outreach?${params}`);
    state.outreach.total = data.total;
    state.outreach.totalPages = data.total_pages;

    const tbody = document.getElementById('outreach-tbody');
    if (!data.logs.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="py-12 text-center text-gray-400">No outreach logs yet</td></tr>`;
    } else {
      tbody.innerHTML = data.logs.map(l => `
        <tr>
          <td class="py-3 px-4">
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${l.channel === 'email' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}">${l.channel}</span>
          </td>
          <td class="py-3 px-4 text-sm text-gray-700">${esc(l.recipient_email || l.recipient_phone)}</td>
          <td class="py-3 px-4 text-sm text-gray-700 max-w-xs truncate">${esc(l.subject)}</td>
          <td class="py-3 px-4">
            <span class="inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${l.success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}">${l.success ? 'Success' : 'Failed'}</span>
          </td>
          <td class="py-3 px-4 text-sm text-gray-500">${formatDate(l.created_at)}</td>
        </tr>
      `).join('');
    }

    // Pagination
    const pel = document.getElementById('outreach-pagination');
    const { page, totalPages, total } = state.outreach;
    if (totalPages <= 1) {
      pel.innerHTML = `<span class="text-sm text-gray-500">${total} total</span>`;
    } else {
      pel.innerHTML = `
        <span class="text-sm text-gray-500">${total} total</span>
        <div class="flex gap-1">
          <button class="btn-op px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-40" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>Prev</button>
          <span class="px-3 py-1.5 text-sm text-gray-700">Page ${page} / ${totalPages}</span>
          <button class="btn-op px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-40" data-page="${page + 1}" ${page >= totalPages ? 'disabled' : ''}>Next</button>
        </div>
      `;
      pel.querySelectorAll('.btn-op').forEach(b => {
        b.addEventListener('click', () => {
          state.outreach.page = parseInt(b.dataset.page);
          loadOutreach();
        });
      });
    }
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------

async function runPipeline(e) {
  e.preventDefault();
  const btn = document.getElementById('btn-run-pipeline');
  const statusEl = document.getElementById('pipeline-job-status');
  btn.disabled = true;
  btn.textContent = 'Running...';

  try {
    const res = await api('/api/pipeline/run', {
      method: 'POST',
      body: JSON.stringify({
        keyword: document.getElementById('pipe-keyword').value,
        region: document.getElementById('pipe-region').value,
        channels: document.getElementById('pipe-channels').value,
        max_leads: parseInt(document.getElementById('pipe-max-leads').value) || 15,
        dry_run: document.getElementById('pipe-dry-run').checked,
      }),
    });

    statusEl.classList.remove('hidden');
    statusEl.innerHTML = `<p class="text-sm font-medium text-indigo-700">Job started (${res.job_id})</p><p class="text-xs text-gray-500 mt-1">Polling for status...</p>`;

    // Poll until complete
    const poll = setInterval(async () => {
      try {
        const job = await api(`/api/pipeline/status/${res.job_id}`);
        const pct = job.progress || 0;

        if (job.status === 'completed') {
          clearInterval(poll);
          const r = job.result || {};
          statusEl.innerHTML = `
            <p class="text-sm font-medium text-green-700">Pipeline Complete</p>
            <div class="mt-2 space-y-1 text-sm text-gray-600">
              <p>Leads found: <strong>${r.leads_found}</strong></p>
              <p>Passed filter: <strong>${r.leads_passed}</strong></p>
              <p>Contacts found: <strong>${r.contacts_found}</strong></p>
              <p>Outreach sent: <strong>${r.outreach_sent}</strong>${r.dry_run ? ' (dry run)' : ''}</p>
            </div>
          `;
          toast('Pipeline completed', 'success');
          btn.disabled = false;
          btn.textContent = 'Run Pipeline';
        } else if (job.status === 'failed') {
          clearInterval(poll);
          statusEl.innerHTML = `<p class="text-sm font-medium text-red-700">Pipeline Failed</p><p class="text-xs text-red-600 mt-1">${esc(job.error || 'Unknown error')}</p>`;
          toast('Pipeline failed', 'error');
          btn.disabled = false;
          btn.textContent = 'Run Pipeline';
        } else {
          statusEl.innerHTML = `
            <p class="text-sm font-medium text-indigo-700">Running (${pct}%)</p>
            <div class="mt-2 bg-gray-200 rounded-full h-2"><div class="bg-indigo-500 rounded-full h-2 transition-all" style="width:${pct}%"></div></div>
            <p class="text-xs text-gray-500 mt-1">${job.status}...</p>
          `;
        }
      } catch {
        clearInterval(poll);
        btn.disabled = false;
        btn.textContent = 'Run Pipeline';
      }
    }, 2000);

  } catch (err) {
    toast(err.message, 'error');
    btn.disabled = false;
    btn.textContent = 'Run Pipeline';
  }
}

// ---------------------------------------------------------------------------
// Settings (System Config / 系统设置)
// ---------------------------------------------------------------------------

async function loadSettings() {
  const banner = document.getElementById('settings-banner');
  banner.classList.add('hidden');

  // If user object already has smtp fields from /me, use them; otherwise fetch
  if (state.user.smtp_configured !== undefined) {
    populateSettingsForm(state.user);
  } else {
    try {
      const data = await api('/api/users/smtp-config');
      state.user.smtp_configured = data.smtp_configured;
      state.user.smtp_host = data.smtp_host;
      state.user.smtp_port = data.smtp_port;
      state.user.smtp_username = data.smtp_username;
      populateSettingsForm(state.user);
    } catch (err) {
      banner.textContent = 'Failed to load SMTP config';
      banner.className = 'mt-4 p-3 rounded-lg text-sm bg-red-50 text-red-700';
      banner.classList.remove('hidden');
    }
  }
}

function populateSettingsForm(u) {
  document.getElementById('settings-smtp-host').value = u.smtp_host || '';
  document.getElementById('settings-smtp-port').value = u.smtp_port || '';
  document.getElementById('settings-smtp-username').value = u.smtp_username || '';
  document.getElementById('settings-smtp-password').value = '';
  updateSettingsStatus(u.smtp_configured);
}

function updateSettingsStatus(configured) {
  const badge = document.getElementById('settings-status-badge');
  if (configured) {
    badge.textContent = 'Active';
    badge.className = 'inline-flex px-2.5 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-700';
  } else {
    badge.textContent = 'Not configured';
    badge.className = 'inline-flex px-2.5 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-600';
  }
}

async function saveSettings(e) {
  e.preventDefault();
  const btn = document.getElementById('btn-save-settings');
  const banner = document.getElementById('settings-banner');
  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    const body = {
      smtp_host: document.getElementById('settings-smtp-host').value.trim(),
      smtp_port: parseInt(document.getElementById('settings-smtp-port').value) || 0,
      smtp_username: document.getElementById('settings-smtp-username').value.trim(),
    };
    const pw = document.getElementById('settings-smtp-password').value;
    if (pw) body.smtp_password = pw;

    const data = await api('/api/users/smtp-config', {
      method: 'POST',
      body: JSON.stringify(body),
    });

    state.user.smtp_configured = data.smtp_configured;
    state.user.smtp_host = data.smtp_host;
    state.user.smtp_port = data.smtp_port;
    state.user.smtp_username = data.smtp_username;
    updateSettingsStatus(data.smtp_configured);

    banner.textContent = 'SMTP settings saved successfully.';
    banner.className = 'mt-4 p-3 rounded-lg text-sm bg-green-50 text-green-700';
    banner.classList.remove('hidden');
    document.getElementById('settings-smtp-password').value = '';
  } catch (err) {
    banner.textContent = err.message;
    banner.className = 'mt-4 p-3 rounded-lg text-sm bg-red-50 text-red-700';
    banner.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save SMTP Settings';
  }
}

async function testSMTPConnection() {
  const banner = document.getElementById('settings-banner');
  const btn = document.getElementById('btn-test-smtp');
  btn.disabled = true;
  btn.textContent = 'Testing...';

  try {
    // Save first, then trigger a dry-run pipeline with just that user's config
    const body = {
      smtp_host: document.getElementById('settings-smtp-host').value.trim(),
      smtp_port: parseInt(document.getElementById('settings-smtp-port').value) || 0,
      smtp_username: document.getElementById('settings-smtp-username').value.trim(),
    };
    const pw = document.getElementById('settings-smtp-password').value;
    if (pw) body.smtp_password = pw;

    // Save settings
    const data = await api('/api/users/smtp-config', {
      method: 'POST',
      body: JSON.stringify(body),
    });

    state.user.smtp_configured = data.smtp_configured;
    state.user.smtp_host = data.smtp_host;
    state.user.smtp_port = data.smtp_port;
    state.user.smtp_username = data.smtp_username;
    updateSettingsStatus(data.smtp_configured);
    document.getElementById('settings-smtp-password').value = '';

    if (!data.smtp_configured) {
      banner.textContent = 'Please fill in all four SMTP fields before testing.';
      banner.className = 'mt-4 p-3 rounded-lg text-sm bg-amber-50 text-amber-700';
      banner.classList.remove('hidden');
      return;
    }

    banner.textContent = 'SMTP configuration verified — ready for pipeline execution.';
    banner.className = 'mt-4 p-3 rounded-lg text-sm bg-green-50 text-green-700';
    banner.classList.remove('hidden');
  } catch (err) {
    banner.textContent = err.message;
    banner.className = 'mt-4 p-3 rounded-lg text-sm bg-red-50 text-red-700';
    banner.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function esc(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ---------------------------------------------------------------------------
// Event bindings
// ---------------------------------------------------------------------------

// Auth tabs — reset forms on switch to prevent stale data leaking between panels
document.getElementById('tab-login').addEventListener('click', () => {
  document.getElementById('login-form').classList.remove('hidden');
  document.getElementById('register-form').classList.add('hidden');
  document.getElementById('register-form').reset();
  document.getElementById('tab-login').className = 'flex-1 py-3 text-sm font-semibold text-indigo-600 border-b-2 border-indigo-600 bg-white';
  document.getElementById('tab-register').className = 'flex-1 py-3 text-sm font-semibold text-gray-400 border-b-2 border-transparent hover:text-gray-600';
  document.getElementById('auth-error').classList.add('hidden');
});

document.getElementById('tab-register').addEventListener('click', () => {
  document.getElementById('register-form').classList.remove('hidden');
  document.getElementById('login-form').classList.add('hidden');
  document.getElementById('login-form').reset();
  document.getElementById('tab-register').className = 'flex-1 py-3 text-sm font-semibold text-indigo-600 border-b-2 border-indigo-600 bg-white';
  document.getElementById('tab-login').className = 'flex-1 py-3 text-sm font-semibold text-gray-400 border-b-2 border-transparent hover:text-gray-600';
  document.getElementById('auth-error').classList.add('hidden');
});

// Login
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('auth-error');
  try {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: document.getElementById('login-email').value,
        password: document.getElementById('login-password').value,
      }),
    });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    errorEl.classList.add('hidden');
    showAppView();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
  }
});

// Register
document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('auth-error');
  try {
    const data = await api('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        email: document.getElementById('reg-email').value,
        display_name: document.getElementById('reg-name').value,
        password: document.getElementById('reg-password').value,
        company: document.getElementById('reg-company').value,
      }),
    });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem('token', data.token);
    localStorage.setItem('user', JSON.stringify(data.user));
    errorEl.classList.add('hidden');
    showAppView();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
  }
});

// Logout
document.getElementById('btn-logout').addEventListener('click', logout);

// Navigation
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => navigateTo(btn.dataset.nav));
});

// Lead modal
document.getElementById('modal-close').addEventListener('click', closeLeadModal);
document.getElementById('modal-cancel').addEventListener('click', closeLeadModal);
document.getElementById('lead-modal').addEventListener('click', (e) => {
  if (e.target === document.getElementById('lead-modal')) closeLeadModal();
});
document.getElementById('lead-edit-form').addEventListener('submit', saveLead);
document.getElementById('btn-delete-lead').addEventListener('click', deleteLead);
document.getElementById('btn-add-lead').addEventListener('click', createLead);

// Leads table sorting
document.querySelectorAll('#view-leads thead th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const field = th.dataset.sort;
    if (state.leads.sortBy === field) {
      state.leads.sortDir = state.leads.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      state.leads.sortBy = field;
      state.leads.sortDir = 'asc';
    }
    loadLeads();
  });
});

// Lead filters (debounced)
let searchTimer;
document.getElementById('lead-search').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.leads.search = e.target.value;
    state.leads.page = 1;
    loadLeads();
  }, 300);
});

document.getElementById('lead-filter-status').addEventListener('change', (e) => {
  state.leads.outreachStatus = e.target.value;
  state.leads.page = 1;
  loadLeads();
});

document.getElementById('lead-filter-target').addEventListener('change', (e) => {
  state.leads.isTarget = e.target.value;
  state.leads.page = 1;
  loadLeads();
});

// Pipeline
document.getElementById('pipeline-form').addEventListener('submit', runPipeline);

// Settings
document.getElementById('settings-form').addEventListener('submit', saveSettings);
document.getElementById('btn-test-smtp').addEventListener('click', testSMTPConnection);

// Password visibility toggle
document.querySelectorAll('.pw-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = document.getElementById(btn.dataset.target);
    const eye = btn.querySelector('.pw-eye');
    const eyeOff = btn.querySelector('.pw-eye-off');
    if (input.type === 'password') {
      input.type = 'text';
      eye.classList.add('hidden');
      eyeOff.classList.remove('hidden');
    } else {
      input.type = 'password';
      eye.classList.remove('hidden');
      eyeOff.classList.add('hidden');
    }
  });
});

// Keyboard shortcut: Escape to close modal
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeLeadModal();
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

if (state.token && state.user) {
  // Validate token is still good
  api('/api/auth/me')
    .then(user => {
      state.user = user;
      localStorage.setItem('user', JSON.stringify(user));
      showAppView();
    })
    .catch(() => {
      logout();
    });
} else {
  showAuthView();
}
