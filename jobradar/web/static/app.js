/**
 * JobRadar - Executive Career Intelligence Application Logic
 * Refined Light Slate & Warm Porcelain Design System (Calm, Non-Shouty)
 */

let state = {
  status: 'new',
  track: 'all',
  minScore: null,
  source: 'all',
  search: '',
  limit: 150,
  sortBy: 'score',
};

let currentJobs = {};
let activeModalJobId = null;
let debounceTimer = null;

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  loadStats();
  loadSources();
  loadJobs();
});

function initEventListeners() {
  // Application status segment pills
  document.querySelectorAll('.status-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.status-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.status = btn.dataset.status;
      loadJobs();
    });
  });

  // Notion Sync button
  const syncBtn = document.getElementById('sync-notion-btn');
  if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
      syncBtn.classList.add('sync-spinning');
      try {
        const res = await fetch('/api/notion/sync', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          alert(`🔄 Notion Sync Complete!\n• Rows Scanned: ${data.summary.notion_rows_scanned}\n• Jobs Updated: ${data.summary.synced_jobs}\n• Links Backfilled: ${data.summary.backfilled_links}`);
          loadStats();
          loadJobs();
        } else {
          alert(`⚠️ ${data.message || 'Notion sync could not be completed.'}`);
        }
      } catch (err) {
        console.error('Failed to sync with Notion:', err);
        alert('Could not connect to the Notion sync service.');
      } finally {
        syncBtn.classList.remove('sync-spinning');
      }
    });
  }

  // Track tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.track = btn.dataset.track;

      if (state.track !== 'all') {
        const scoreFilter = document.getElementById('score-filter');
        if (scoreFilter && scoreFilter.value !== 'all') {
          scoreFilter.value = 'all';
          state.minScore = null;
        }
      }
      loadJobs();
    });
  });


  // Score threshold filter
  const scoreFilter = document.getElementById('score-filter');
  if (scoreFilter) {
    scoreFilter.addEventListener('change', (e) => {
      const val = e.target.value;
      if (val === 'matches') {
        state.minScore = 9.0;
      } else if (val === 'near_misses') {
        state.minScore = 6.5;
      } else {
        state.minScore = null;
      }
      loadJobs();
    });
  }

  // Source filter
  const sourceFilter = document.getElementById('source-filter');
  if (sourceFilter) {
    sourceFilter.addEventListener('change', (e) => {
      state.source = e.target.value;
      loadJobs();
    });
  }

  // Search input with debounce
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        state.search = e.target.value;
        loadJobs();
      }, 300);
    });
  }

  // Trigger Run button
  const triggerBtn = document.getElementById('trigger-run-btn');
  if (triggerBtn) {
    triggerBtn.addEventListener('click', handleTriggerRun);
  }

  // Refresh Feed button
  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      loadStats();
      loadJobs();
      showToast('Feed refreshed');
    });
  }

  // Add Employer modal
  const addEmpBtn = document.getElementById('add-employer-btn');
  const addEmpModal = document.getElementById('add-employer-modal');
  const addEmpClose = document.getElementById('add-employer-modal-close');
  if (addEmpBtn && addEmpModal) {
    addEmpBtn.addEventListener('click', () => {
      addEmpModal.classList.add('active');
      const nameInput = document.getElementById('new-source-name');
      if (nameInput) nameInput.focus();
    });
  }
  if (addEmpClose && addEmpModal) {
    addEmpClose.addEventListener('click', () => addEmpModal.classList.remove('active'));
    addEmpModal.addEventListener('click', (e) => {
      if (e.target === addEmpModal) addEmpModal.classList.remove('active');
    });
  }

  // Modal close
  const modalClose = document.getElementById('modal-close');
  const modalOverlay = document.getElementById('modal-overlay');
  if (modalClose && modalOverlay) {
    modalClose.addEventListener('click', () => modalOverlay.classList.remove('active'));
    modalOverlay.addEventListener('click', (e) => {
      if (e.target === modalOverlay) modalOverlay.classList.remove('active');
    });
  }

  // Keyboard shortcut: Escape to close modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (modalOverlay && modalOverlay.classList.contains('active')) modalOverlay.classList.remove('active');
      if (addEmpModal && addEmpModal.classList.contains('active')) addEmpModal.classList.remove('active');
    }
  });
}

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();
    
    document.getElementById('stat-total-jobs').textContent = data.total_jobs || '0';
    const appliedEl = document.getElementById('stat-applied-jobs');
    if (appliedEl) appliedEl.textContent = data.applied_count || '0';
    document.getElementById('stat-high-matches').textContent = data.high_matches || '0';
    document.getElementById('stat-near-misses').textContent = data.near_misses || '0';
    document.getElementById('stat-active-sources').textContent = data.active_sources || '0';
    document.getElementById('stat-avg-score').textContent = (data.top10_avg_score || 0).toFixed(1);
  } catch (err) {
    console.error('Failed to load stats:', err);
  }
}

async function loadSources() {
  try {
    const res = await fetch('/api/sources');
    if (!res.ok) return;
    const data = await res.json();
    const select = document.getElementById('source-filter');
    if (!select) return;

    select.innerHTML = '<option value="all">All Portals & Sources</option>';

    data.sources.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.id;
      const customTag = s.custom ? ' ★' : '';
      const statusTag = s.enabled ? '' : ' (Paused)';
      opt.textContent = `${s.name}${customTag}${statusTag}`;
      select.appendChild(opt);
    });
  } catch (err) {
    console.error('Failed to load sources:', err);
  }
}

async function loadJobs() {
  const container = document.getElementById('jobs-grid');
  const countEl = document.getElementById('jobs-count-text');
  if (!container) return;

  container.innerHTML = `
    <div style="text-align: center; padding: 4rem 1rem; color: var(--text-dim);">
      <div class="pulse-dot" style="margin: 0 auto 1.25rem auto; width: 8px; height: 8px; background: #94A3B8;"></div>
      <div style="font-size: 0.85rem; font-family: var(--font-mono); letter-spacing: 0.05em; text-transform: uppercase;">Retrieving job postings...</div>
    </div>
  `;

  const params = new URLSearchParams();
  if (state.status) params.set('status', state.status);
  if (state.track && state.track !== 'all') params.set('track', state.track);
  if (state.minScore !== null) params.set('min_score', state.minScore);
  if (state.source && state.source !== 'all') params.set('source', state.source);
  if (state.search) params.set('search', state.search);
  params.set('limit', state.limit);

  try {
    const res = await fetch(`/api/jobs?${params.toString()}`);
    if (!res.ok) throw new Error('API error');
    const data = await res.json();

    if (countEl) {
      countEl.innerHTML = `Showing <b>${data.count}</b> verified vacancies matching criteria`;
    }

    if (!data.jobs || data.jobs.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem 1.5rem; background: var(--bg-surface); border: 1px dashed var(--border-card); border-radius: var(--radius-md); margin: 1rem 0;">
          <h3 style="font-size: 1.1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.35rem;">No matching vacancies found</h3>
          <p style="font-size: 0.85rem; color: var(--text-muted); max-width: 440px; margin: 0 auto 1.25rem auto; line-height: 1.6;">
            Try switching to "All Postings", loosening your keyword query, or resetting the score filter.
          </p>
          <button class="btn btn-ghost" onclick="resetFilters()">Reset All Filters</button>
        </div>
      `;
      return;
    }

    currentJobs = {};
    data.jobs.forEach(j => {
      currentJobs[j.id] = j;
    });

    container.innerHTML = data.jobs.map((job) => renderJobCard(job)).join('');
  } catch (err) {
    console.error('Failed to load jobs:', err);
    container.innerHTML = `
      <div style="text-align: center; padding: 3rem 1.5rem; background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--radius-md);">
        <h3 style="font-size: 1.05rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.35rem;">Unable to load feed</h3>
        <p style="font-size: 0.825rem; color: var(--text-muted);">Could not reach the database backend. Check service status.</p>
      </div>
    `;
  }
}

function renderJobCard(job) {
  const isMatch = job.final_score >= 9.0;
  const isNearMiss = !isMatch && job.final_score >= 6.5;

  let cardClass = 'job-card';
  if (isMatch) cardClass += ' is-match';
  else if (isNearMiss) cardClass += ' is-near-miss';

  let pillHtml = '';
  if (isMatch) {
    pillHtml = `<div class="score-pill match"><span>${job.final_score.toFixed(1)}</span> <span style="font-size: 0.65rem; opacity: 0.85;">MATCH</span></div>`;
  } else if (isNearMiss) {
    pillHtml = `<div class="score-pill near-miss"><span>${job.final_score.toFixed(1)}</span> <span style="font-size: 0.65rem; opacity: 0.85;">NEAR</span></div>`;
  } else {
    pillHtml = `<div class="score-pill low"><span>${job.final_score.toFixed(1)}</span></div>`;
  }

  const trackClass = `track-tag ${job.best_track_id || 'general'}`;
  
  // Format breakdown chips
  const breakdown = job.breakdown || {};
  const chips = [];
  
  if (breakdown.tech_matches && breakdown.tech_matches.length > 0) {
    breakdown.tech_matches.slice(0, 4).forEach(k => {
      chips.push(`<span class="chip pos">✓ ${escapeHtml(k)}</span>`);
    });
  }

  if (breakdown.location_bonus > 0) {
    chips.push(`<span class="chip loc">+${breakdown.location_bonus.toFixed(1)} Hub</span>`);
  }

  if (breakdown.seniority_bonus > 0) {
    chips.push(`<span class="chip pos">+${breakdown.seniority_bonus.toFixed(1)} Seniority</span>`);
  }

  const postedText = job.first_seen ? formatRelativeTime(job.first_seen) : 'Recently';
  const fullDesc = job.full_description || job.description || 'No detailed requirements provided.';

  const appStatus = (job.application_status || 'unapplied').toLowerCase();
  const isApplied = ['applied', 'screening', 'interview', 'final round', 'final_round', 'offer'].includes(appStatus);
  const isClosed = ['rejected', 'withdrawn', 'no_response', 'closed'].includes(appStatus) || job.is_closed;

  let applyButtonHtml = '';
  if (isApplied) {
    applyButtonHtml = `
      <button class="btn-apply is-applied" title="Synced with Notion. Click to unapply." onclick="event.stopPropagation(); updateJobStatus(${job.id}, 'unapplied')">
        ✓ ${escapeHtml(job.application_status)}
      </button>
    `;
  } else if (isClosed) {
    applyButtonHtml = `
      <button class="btn-apply" title="Archived. Click to reopen." onclick="event.stopPropagation(); updateJobStatus(${job.id}, 'unapplied')">
        Archived
      </button>
    `;
  } else {
    applyButtonHtml = `
      <button class="btn-apply" title="Mark applied and sync to Notion" onclick="event.stopPropagation(); updateJobStatus(${job.id}, 'Applied')">
        + Mark Applied
      </button>
    `;
  }

  return `
    <div class="${cardClass}" id="job-card-${job.id}">
      <div class="job-top-bar">
        <div class="company-meta">
          <span class="company-name">${escapeHtml(job.company)}</span>
          <span class="source-badge">${escapeHtml(formatSourceName(job.source))}</span>
          <span class="posted-badge">${postedText}</span>
          ${job.notion_page_id ? `<span class="source-badge" style="background: #EEF2FF; color: #4F46E5; border-color: #C7D2FE;" title="Synced with Notion Job Applications">Notion</span>` : ''}
        </div>
        ${pillHtml}
      </div>

      <h3 class="job-title" onclick="openJobModal(${job.id}, 'requirements')" style="cursor: pointer;">${escapeHtml(job.title)}</h3>

      <div class="job-meta-row">
        <span class="meta-pill">
          <svg viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
          ${escapeHtml(job.location)}
        </span>
        <span class="${trackClass}">${escapeHtml(job.best_track_name || 'General')}</span>
      </div>

      <p class="job-snippet">${escapeHtml(job.description || '')}</p>

      ${chips.length > 0 ? `<div class="breakdown-chips">${chips.join('')}</div>` : ''}

      <div class="card-actions">
        <div class="action-buttons-left">
          ${applyButtonHtml}
          <button class="btn-toggle-req" id="btn-toggle-${job.id}" onclick="toggleRequirements(${job.id})">
            Details & Requirements <span class="req-arrow">▾</span>
          </button>
          <button class="btn-inspect" onclick="openJobModal(${job.id}, 'breakdown')">
            Match Telemetry
          </button>

          ${job.breakdown?.ai_insight ? `
          <button class="btn-inspect btn-ai" onclick="openJobModal(${job.id}, 'ai')">
            ✦ AI Copilot (${job.breakdown.ai_insight.semantic_fit_score}%)
          </button>` : `
          <button class="btn-inspect btn-ai" onclick="openJobModal(${job.id}, 'ai')">
            ✦ AI Copilot
          </button>`}
        </div>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="apply-link">
          Apply on Portal ↗
        </a>
      </div>

      <div class="job-req-drawer" id="req-drawer-${job.id}" style="display: none;">
        <div class="job-req-drawer-header">
          <span class="req-header-title">Role Specifications & Requirements</span>
          <button class="btn-hide-req" onclick="toggleRequirements(${job.id})">Hide ▴</button>
        </div>
        <div class="req-drawer-body">
          ${formatDescriptionHtml(fullDesc)}
        </div>
        <div class="req-drawer-footer">
          <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary" style="font-size: 0.8rem; padding: 0.45rem 1rem;">
            Open Official Vacancy ↗
          </a>
        </div>
      </div>
    </div>
  `;
}

function toggleRequirements(jobId) {
  const drawer = document.getElementById(`req-drawer-${jobId}`);
  const btn = document.getElementById(`btn-toggle-${jobId}`);
  if (!drawer || !btn) return;

  const isOpen = drawer.style.display !== 'none';
  if (isOpen) {
    drawer.style.display = 'none';
    btn.classList.remove('open');
    btn.innerHTML = `Details & Requirements <span class="req-arrow">▾</span>`;
  } else {
    drawer.style.display = 'block';
    btn.classList.add('open');
    btn.innerHTML = `Hide Details <span class="req-arrow">▴</span>`;
  }
}

function openJobModal(jobId, initialTab = 'requirements') {
  const job = currentJobs[jobId];
  if (!job) return;

  activeModalJobId = jobId;
  const modal = document.getElementById('modal-overlay');
  const title = document.getElementById('modal-job-title');
  const content = document.getElementById('modal-job-content');
  if (!modal || !title || !content) return;

  title.textContent = `${job.title} · ${job.company}`;

  const aiInsight = job.breakdown?.ai_insight;
  const currentStatus = job.application_status || 'unapplied';

  content.innerHTML = `
    <!-- Notion Application Status Action Bar -->
    <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem; padding: 0.75rem 1rem; margin-bottom: 1.25rem; background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--radius-sm);">
      <div style="display: flex; align-items: center; gap: 0.6rem;">
        <span style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Application Status:</span>
        <select id="modal-status-select" onchange="window.updateJobStatus(${job.id}, this.value)" style="padding: 0.35rem 0.65rem; font-size: 0.8rem; font-weight: 600; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); background: var(--bg-card); color: var(--text-primary); cursor: pointer;">
          <option value="unapplied" ${currentStatus.toLowerCase() === 'unapplied' ? 'selected' : ''}>Fresh / Unapplied</option>
          <option value="To apply" ${currentStatus === 'To apply' ? 'selected' : ''}>To apply</option>
          <option value="Applied" ${currentStatus === 'Applied' ? 'selected' : ''}>Applied</option>
          <option value="Screening" ${currentStatus === 'Screening' ? 'selected' : ''}>Screening</option>
          <option value="Interview" ${currentStatus === 'Interview' ? 'selected' : ''}>Interview</option>
          <option value="Final round" ${currentStatus === 'Final round' ? 'selected' : ''}>Final round</option>
          <option value="Offer" ${currentStatus === 'Offer' ? 'selected' : ''}>Offer</option>
          <option value="Rejected" ${currentStatus === 'Rejected' ? 'selected' : ''}>Rejected</option>
          <option value="Withdrawn" ${currentStatus === 'Withdrawn' ? 'selected' : ''}>Withdrawn</option>
        </select>
      </div>
      <div style="font-size: 0.75rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.4rem;">
        ${job.notion_page_id ? `
          <span style="display: inline-flex; align-items: center; gap: 0.35rem; color: #4F46E5; font-weight: 600;">
            <span style="display:inline-block; width: 6px; height: 6px; border-radius: 50%; background: #4F46E5;"></span> Synced to Notion Tracker
          </span>
        ` : `
          <span style="color: var(--text-dim);">Changes automatically push to Notion</span>
        `}
      </div>
    </div>

    <div class="modal-nav-tabs">
      <button class="modal-nav-btn ${initialTab === 'requirements' ? 'active' : ''}" id="modal-tab-req" onclick="switchModalTab('requirements')">
        Role Requirements
      </button>
      <button class="modal-nav-btn ${initialTab === 'breakdown' ? 'active' : ''}" id="modal-tab-score" onclick="switchModalTab('breakdown')">
        Match Telemetry
      </button>
      <button class="modal-nav-btn modal-tab-ai ${initialTab === 'ai' ? 'active' : ''}" id="modal-tab-ai" onclick="switchModalTab('ai')">
        ✦ AI Copilot ${aiInsight ? `(${aiInsight.semantic_fit_score}%)` : ''}
      </button>
    </div>

    <!-- Pane 1: Role Requirements -->
    <div id="modal-pane-requirements" style="display: ${initialTab === 'requirements' ? 'block' : 'none'};">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; padding: 0.75rem 1rem; background: var(--bg-subtle); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); font-size: 0.8rem;">
        <div>
          <span style="color: var(--text-muted);">Source: <b style="color: var(--text-primary);">${escapeHtml(formatSourceName(job.source))}</b></span>
          <span style="margin: 0 0.5rem; color: var(--border-subtle);">|</span>
          <span style="color: var(--text-muted);">Location: <b style="color: var(--text-primary);">${escapeHtml(job.location)}</b></span>
        </div>
        <span class="track-tag ${job.best_track_id || 'general'}">${escapeHtml(job.best_track_name || 'General')}</span>
      </div>

      <div class="req-drawer-body" style="max-height: 50vh; padding-right: 0.5rem;">
        ${formatDescriptionHtml(job.full_description || job.description)}
      </div>

      <div style="margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 1rem; border-top: 1px solid var(--border-subtle);">
        <button class="btn btn-ghost" onclick="switchModalTab('breakdown')">Match Telemetry →</button>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
          Apply on Portal ↗
        </a>
      </div>
    </div>

    <!-- Pane 2: Match Architecture Telemetry -->
    <div id="modal-pane-breakdown" style="display: ${initialTab === 'breakdown' ? 'block' : 'none'};">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; padding: 1.2rem; background: var(--bg-surface); border-radius: var(--radius-md); border: 1px solid var(--border-card);">
        <div>
          <div style="font-size: 0.7rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Evaluated Persona Track</div>
          <div style="font-size: 1.15rem; font-weight: 800; color: var(--text-primary);">${escapeHtml(job.best_track_name || 'General Tech')}</div>
        </div>
        <div style="text-align: right;">
          <div style="font-size: 0.7rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Match Score</div>
          <div style="font-size: 1.75rem; font-weight: 800; font-family: var(--font-mono); color: #15803D;">${job.final_score.toFixed(1)}</div>
        </div>
      </div>

      <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; color: var(--text-muted); font-family: var(--font-mono);">Scoring Weights & Criteria:</div>
      <div class="telemetry-grid">
        <div class="telemetry-item">
          <div class="telemetry-label">Track Tech Match</div>
          <div class="telemetry-value">+${(job.breakdown?.best_track_score || 0).toFixed(1)}</div>
        </div>
        <div class="telemetry-item">
          <div class="telemetry-label">Location Proximity (${escapeHtml(job.location)})</div>
          <div class="telemetry-value">+${(job.breakdown?.location_bonus || 0).toFixed(1)}</div>
        </div>
        <div class="telemetry-item">
          <div class="telemetry-label">Seniority Tier Alignment</div>
          <div class="telemetry-value">+${(job.breakdown?.seniority_bonus || 0).toFixed(1)}</div>
        </div>
        <div class="telemetry-item">
          <div class="telemetry-label">Disqualification Penalties</div>
          <div class="telemetry-value ${(job.breakdown?.penalties || 0) > 0 ? 'negative' : ''}">-${(job.breakdown?.penalties || 0).toFixed(1)}</div>
        </div>
      </div>

      <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin: 1.25rem 0 0.5rem 0; color: var(--text-muted); font-family: var(--font-mono);">Verified Profile Keywords:</div>
      <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
        ${(job.breakdown?.tech_matches || []).map(k => `<span class="chip pos" style="font-size: 0.8rem; padding: 0.35rem 0.7rem;">✓ ${escapeHtml(k)}</span>`).join('') || '<span style="color: var(--text-dim); font-size: 0.825rem;">None</span>'}
      </div>

      <div style="margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 1rem; border-top: 1px solid var(--border-subtle);">
        <button class="btn btn-ghost" onclick="switchModalTab('requirements')">← Requirements</button>
        <button class="btn btn-ghost" onclick="switchModalTab('ai')" style="color: var(--copilot-text);">✦ Open AI Copilot</button>
      </div>
    </div>

    <!-- Pane 3: AI Career Copilot -->
    <div id="modal-pane-ai" style="display: ${initialTab === 'ai' ? 'block' : 'none'};">
      ${aiInsight ? `
      <div class="dossier-card ai-highlight" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem;">
        <div>
          <div style="font-size: 0.7rem; font-weight: 700; color: var(--copilot-text); text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Executive Dossier</div>
          <div style="font-size: 1.15rem; font-weight: 800; color: var(--text-primary);">Semantic Profile Alignment</div>
        </div>
        <div style="text-align: right;">
          <div style="font-size: 0.7rem; font-weight: 700; color: var(--copilot-text); text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Fit Score</div>
          <div style="font-size: 1.95rem; font-weight: 800; font-family: var(--font-mono); color: var(--copilot-text);">${aiInsight.semantic_fit_score}%</div>
        </div>
      </div>

      <div style="margin-bottom: 1.25rem;">
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.45rem; color: var(--text-muted); font-family: var(--font-mono);">Strategic Fit Thesis:</div>
        <div style="background: var(--bg-surface); border: 1px solid var(--border-card); border-radius: var(--radius-sm); padding: 1rem 1.15rem; font-size: 0.875rem; line-height: 1.65; color: var(--text-secondary);">
          ${escapeHtml(aiInsight.fit_rationale)}
        </div>
      </div>

      ${(aiInsight.key_strengths || []).length > 0 ? `
      <div style="margin-bottom: 1.25rem;">
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.45rem; color: var(--text-muted); font-family: var(--font-mono);">Key Leverage Strengths:</div>
        <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
          ${aiInsight.key_strengths.map(s => `<span class="chip pos" style="font-size: 0.8rem; padding: 0.35rem 0.65rem;">✓ ${escapeHtml(s)}</span>`).join('')}
        </div>
      </div>` : ''}

      ${(aiInsight.skill_gaps || []).length > 0 ? `
      <div style="margin-bottom: 1.25rem;">
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.45rem; color: var(--advisory-text); font-family: var(--font-mono);">Interview Preparation & Tech Gaps:</div>
        <div style="display: flex; flex-wrap: wrap; gap: 0.4rem;">
          ${aiInsight.skill_gaps.map(g => `<span class="chip neg" style="font-size: 0.8rem; padding: 0.35rem 0.65rem;">! ${escapeHtml(g)}</span>`).join('')}
        </div>
      </div>` : ''}

      ${aiInsight.tailored_pitch ? `
      <div style="margin-bottom: 1.25rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.45rem;">
          <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-family: var(--font-mono);">Tailored Executive Elevator Pitch:</div>
          <button id="copy-pitch-btn" class="btn btn-ghost" style="font-size: 0.725rem; padding: 0.2rem 0.6rem;" onclick="copyTailoredPitch(${job.id})">
            📋 Copy Pitch
          </button>
        </div>
        <div class="pitch-memo-box" id="pitch-text-${job.id}">
          "${escapeHtml(aiInsight.tailored_pitch)}"
        </div>
      </div>` : ''}
      ` : `
      <div id="ai-generate-container-${job.id}" style="text-align: center; padding: 2.75rem 1.5rem; background: var(--bg-subtle); border: 1.5px dashed var(--copilot-border); border-radius: var(--radius-md);">
        <h3 style="font-size: 1.15rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.4rem;">Generate AI Career Dossier</h3>
        <p style="font-size: 0.85rem; color: var(--text-muted); max-width: 480px; margin: 0 auto 1.5rem auto; line-height: 1.6;">
          Execute deep semantic profile alignment, uncover interview prep gaps, and generate a tailored CV elevator pitch for this role.
        </p>
        <button id="btn-run-ai-${job.id}" class="btn btn-primary" style="padding: 0.65rem 1.5rem; font-size: 0.875rem; font-weight: 700;" onclick="runAiEvaluation(${job.id})">
          ✦ Run AI Fit Evaluation
        </button>
      </div>
      `}

      <div style="margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 1rem; border-top: 1px solid var(--border-subtle);">
        <button class="btn btn-ghost" onclick="switchModalTab('requirements')">← Requirements</button>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
          Apply on Portal ↗
        </a>
      </div>
    </div>
  `;

  modal.classList.add('active');
}

function switchModalTab(tabName) {
  const reqBtn = document.getElementById('modal-tab-req');
  const scoreBtn = document.getElementById('modal-tab-score');
  const aiBtn = document.getElementById('modal-tab-ai');
  const reqPane = document.getElementById('modal-pane-requirements');
  const scorePane = document.getElementById('modal-pane-breakdown');
  const aiPane = document.getElementById('modal-pane-ai');

  if (tabName === 'requirements') {
    if (reqBtn) reqBtn.classList.add('active');
    if (scoreBtn) scoreBtn.classList.remove('active');
    if (aiBtn) aiBtn.classList.remove('active');
    if (reqPane) reqPane.style.display = 'block';
    if (scorePane) scorePane.style.display = 'none';
    if (aiPane) aiPane.style.display = 'none';
  } else if (tabName === 'breakdown') {
    if (reqBtn) reqBtn.classList.remove('active');
    if (scoreBtn) scoreBtn.classList.add('active');
    if (aiBtn) aiBtn.classList.remove('active');
    if (reqPane) reqPane.style.display = 'none';
    if (scorePane) scorePane.style.display = 'block';
    if (aiPane) aiPane.style.display = 'none';
  } else if (tabName === 'ai') {
    if (reqBtn) reqBtn.classList.remove('active');
    if (scoreBtn) scoreBtn.classList.remove('active');
    if (aiBtn) aiBtn.classList.add('active');
    if (reqPane) reqPane.style.display = 'none';
    if (scorePane) scorePane.style.display = 'none';
    if (aiPane) aiPane.style.display = 'block';
  }
}

function copyTailoredPitch(jobId) {
  const pitchElem = document.getElementById(`pitch-text-${jobId}`);
  const copyBtn = document.getElementById('copy-pitch-btn');
  if (!pitchElem) return;
  const text = pitchElem.innerText.replace(/^"|"$/g, '').trim();
  navigator.clipboard.writeText(text).then(() => {
    if (copyBtn) copyBtn.textContent = '✓ Copied!';
    showToast('Pitch copied to clipboard');
    setTimeout(() => {
      if (copyBtn) copyBtn.textContent = '📋 Copy Pitch';
    }, 2500);
  });
}

async function runAiEvaluation(jobId) {
  const btn = document.getElementById(`btn-run-ai-${jobId}`);
  if (!btn) return;

  btn.disabled = true;
  btn.innerHTML = `<span class="pulse-dot" style="display:inline-block; margin-right: 8px;"></span> Evaluating via Gemini AI...`;

  try {
    const res = await fetch(`/api/jobs/${jobId}/ai-evaluate`, { method: 'POST' });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Evaluation request failed');
    }
    const data = await res.json();
    if (data.ai_insight) {
      if (!currentJobs[jobId]) currentJobs[jobId] = {};
      if (!currentJobs[jobId].breakdown) currentJobs[jobId].breakdown = {};
      currentJobs[jobId].breakdown.ai_insight = data.ai_insight;

      showToast(`AI fit evaluated: ${data.ai_insight.semantic_fit_score}% match`);

      // Re-render modal in AI tab
      openJobModal(jobId, 'ai');

      // Update the job card in the background feed
      const card = document.getElementById(`job-card-${jobId}`);
      if (card) {
        const temp = document.createElement('div');
        temp.innerHTML = renderJobCard(currentJobs[jobId]);
        card.replaceWith(temp.firstElementChild);
      }
    }
  } catch (err) {
    console.error('AI evaluation failed:', err);
    btn.disabled = false;
    btn.innerHTML = `Evaluation Failed - Click to Retry`;
    showToast(`AI evaluation failed: ${err.message}`, true);
  }
}

async function handleTriggerRun() {
  const btn = document.getElementById('trigger-run-btn');
  if (!btn) return;

  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="pulse-dot"></span> Crawling...`;

  try {
    const res = await fetch('/api/trigger-run', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      const checked = data.summary?.sources_checked || 0;
      const matches = data.summary?.matches_found || 0;
      showToast(`Crawl complete · Checked ${checked} sources · Found ${matches} matches`);
      loadStats();
      loadJobs();
    } else {
      showToast('Crawl error: ' + (data.detail || 'Error'), true);
    }
  } catch (err) {
    showToast('Failed to trigger crawler pipeline', true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

function resetFilters() {
  state.track = 'all';
  state.minScore = null;
  state.source = 'all';
  state.search = '';

  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.track === 'all');
  });

  const scoreFilter = document.getElementById('score-filter');
  if (scoreFilter) scoreFilter.value = 'all';

  const sourceFilter = document.getElementById('source-filter');
  if (sourceFilter) sourceFilter.value = 'all';

  const searchInput = document.getElementById('search-input');
  if (searchInput) searchInput.value = '';

  loadJobs();
}

window.updateJobStatus = async function(jobId, newStatus) {
  try {
    const res = await fetch(`/api/jobs/${jobId}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus })
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.detail || 'Failed to update status', true);
      return;
    }

    if (currentJobs[jobId]) {
      currentJobs[jobId].application_status = data.job.application_status;
      currentJobs[jobId].notion_page_id = data.job.notion_page_id;
      currentJobs[jobId].applied_at = data.job.applied_at;
    }

    const notionNote = data.notion_synced ? ' & synced to Notion' : '';
    showToast(`Status updated to "${data.job.application_status}"${notionNote}`);
    
    // Refresh stats and feed
    loadStats();
    loadJobs();

    // If modal is open for this job, refresh modal
    if (activeModalJobId === jobId) {
      openJobModal(jobId, 'requirements');
    }
  } catch (err) {
    console.error('Failed to update job status:', err);
    showToast('Network error updating job status', true);
  }
};

function formatDescriptionHtml(text) {
  if (!text) return '<p style="color: var(--text-dim);">No detailed description provided.</p>';
  
  if (/<[a-z][\s\S]*>/i.test(text)) {
    let clean = text
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
      .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
      .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '');
    return clean;
  }

  const lines = text.split(/\r?\n/);
  let html = '';
  let inList = false;

  lines.forEach(line => {
    const trimmed = line.trim();
    if (!trimmed) {
      if (inList) {
        html += '</ul>';
        inList = false;
      }
      return;
    }

    if (/^[-*•]\s+/.test(trimmed)) {
      if (!inList) {
        html += '<ul>';
        inList = true;
      }
      const itemContent = trimmed.replace(/^[-*•]\s+/, '');
      html += `<li>${escapeHtml(itemContent)}</li>`;
    } else {
      if (inList) {
        html += '</ul>';
        inList = false;
      }
      html += `<p>${escapeHtml(trimmed)}</p>`;
    }
  });

  if (inList) {
    html += '</ul>';
  }

  return html || `<p>${escapeHtml(text)}</p>`;
}

function formatSourceName(sourceId) {
  if (!sourceId) return 'Direct';
  const map = {
    'remotive': 'Remotive Remote',
    'weworkremotely': 'We Work Remotely',
    'corporate_staffing': 'Corporate Staffing KE',
    'jobwebkenya': 'JobWebKenya',
    'watu_credit': 'Watu Credit',
    'davis_shirtliff': 'Davis & Shirtliff',
    'britam': 'Britam Insurance',
    'coop_bank': 'Co-op Bank Careers',
    'ncba_bank': 'NCBA Group',
    'kpmg_east_africa': 'KPMG East Africa',
    'deloitte_smartrecruiters': 'Deloitte East Africa',
    'pwc_east_africa': 'PwC East Africa',
    'ey_east_africa': 'EY East Africa',
    'pkf_eastern_africa': 'PKF Eastern Africa',
    'kenya_red_cross': 'Kenya Red Cross',
    'kemri_wellcome': 'KEMRI Wellcome',
  };
  return map[sourceId] || sourceId.replace(/_/g, ' ');
}

function formatRelativeTime(dateStr) {
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffHours = Math.floor((now - date) / (1000 * 60 * 60));
    
    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  } catch (e) {
    return 'Recently';
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  if (!toast) return;

  toast.textContent = message;
  toast.style.borderColor = isError ? 'var(--advisory-border)' : 'var(--border-subtle)';
  toast.classList.add('show');

  setTimeout(() => {
    toast.classList.remove('show');
  }, 3500);
}

let currentProbedSource = null;

window.probeSource = async function() {
  const nameInput = document.getElementById('new-source-name');
  const urlInput = document.getElementById('new-source-url');
  const probeBtn = document.getElementById('btn-probe-source');
  const resultContainer = document.getElementById('probe-result-container');
  if (!nameInput || !urlInput || !probeBtn || !resultContainer) return;

  const name = nameInput.value.trim();
  const url = urlInput.value.trim();
  if (!url) return;

  probeBtn.disabled = true;
  probeBtn.innerHTML = `<span class="pulse-dot" style="display:inline-block; margin-right: 6px;"></span> Probing page & testing extraction...`;
  resultContainer.style.display = 'block';
  resultContainer.innerHTML = `
    <div style="text-align: center; padding: 1.5rem; color: var(--text-muted);">
      <div class="pulse-dot" style="margin: 0 auto 0.75rem auto;"></div>
      <div style="font-size: 0.8rem; font-family: var(--font-mono);">Connecting to career portal and evaluating extraction architecture...</div>
    </div>
  `;

  try {
    const res = await fetch('/api/sources/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, url })
    });
    const data = await res.json();

    if (!data.success) {
      resultContainer.innerHTML = `
        <div style="padding: 1rem; background: #FEF2F2; border: 1px solid #FECACA; border-radius: var(--radius-sm); color: #991B1B; font-size: 0.85rem;">
          <div style="font-weight: 700; margin-bottom: 0.25rem;">Extraction Warning</div>
          <div>${escapeHtml(data.error || 'Could not extract vacancies from this URL.')}</div>
        </div>
      `;
      return;
    }

    currentProbedSource = data;

    let sampleCardsHtml = '';
    if (data.sample_jobs && data.sample_jobs.length > 0) {
      sampleCardsHtml = data.sample_jobs.map(j => `
        <div style="padding: 0.65rem 0.85rem; background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;">
          <div>
            <div style="font-weight: 700; font-size: 0.85rem; color: var(--text-primary);">${escapeHtml(j.title)}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(j.location || 'Nairobi, Kenya')}</div>
          </div>
          <a href="${escapeHtml(j.url)}" target="_blank" rel="noopener noreferrer" style="font-size: 0.75rem; color: var(--accent); text-decoration: none; font-weight: 600; white-space: nowrap;">
            Link ↗
          </a>
        </div>
      `).join('');
    } else {
      sampleCardsHtml = `
        <div style="padding: 0.75rem; background: var(--bg-subtle); border-radius: var(--radius-sm); font-size: 0.8rem; color: var(--text-muted); text-align: center;">
          0 immediate active vacancies found. Source will be monitored during regular 3-hour crawl cycles.
        </div>
      `;
    }

    resultContainer.innerHTML = `
      <div style="background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: var(--radius-sm); padding: 0.85rem 1rem; margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="font-size: 0.7rem; font-weight: 700; color: #166534; font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.05em;">Detected Ingestion Architecture</div>
          <div style="font-size: 0.95rem; font-weight: 800; color: #14532D;">${escapeHtml(data.type_label || data.type)}</div>
        </div>
        <div style="text-align: right;">
          <span style="display: inline-block; padding: 0.2rem 0.6rem; background: #DCFCE7; border: 1px solid #86EFAC; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; color: #15803D;">
            ✓ ${data.count} Sample Vacancies Verified
          </span>
        </div>
      </div>

      <div style="margin-bottom: 1rem;">
        <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; font-family: var(--font-mono);">
          Live Sample Extracted Listings:
        </div>
        ${sampleCardsHtml}
      </div>

      <div style="display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border-subtle);">
        <button type="button" class="btn btn-ghost" onclick="document.getElementById('add-employer-modal').classList.remove('active');">Cancel</button>
        <button type="button" class="btn btn-primary" onclick="window.activateProbedSource()" style="background: #16A34A; border-color: #15803D;">
          ✓ Activate Portal & Add to Pipeline
        </button>
      </div>
    `;

  } catch (err) {
    console.error('Probe failed:', err);
    resultContainer.innerHTML = `
      <div style="padding: 1rem; background: #FEF2F2; border: 1px solid #FECACA; border-radius: var(--radius-sm); color: #991B1B; font-size: 0.85rem;">
        Network error probing career portal. Check network connection.
      </div>
    `;
  } finally {
    probeBtn.disabled = false;
    probeBtn.innerHTML = `🔍 Test & Preview Extraction`;
  }
};

window.activateProbedSource = async function() {
  if (!currentProbedSource) return;

  try {
    const res = await fetch('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: currentProbedSource.name,
        url: currentProbedSource.url,
        type: currentProbedSource.type,
        company_identifier: currentProbedSource.company_identifier,
        selectors: currentProbedSource.selectors,
        enabled: true,
      })
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.detail || 'Failed to save source', true);
      return;
    }

    showToast(`✓ Portal "${currentProbedSource.name}" activated and added to crawler!`);
    const modal = document.getElementById('add-employer-modal');
    if (modal) modal.classList.remove('active');

    // Reset inputs
    document.getElementById('new-source-name').value = '';
    document.getElementById('new-source-url').value = '';
    document.getElementById('probe-result-container').style.display = 'none';
    currentProbedSource = null;

    // Refresh source dropdown and stats
    loadSources();
    loadStats();
  } catch (err) {
    console.error('Failed to activate source:', err);
    showToast('Failed to save portal', true);
  }
};
