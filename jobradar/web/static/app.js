/**
 * JobRadar Interactive Web Dashboard Application Logic
 */

let state = {
  track: 'all',
  minScore: null,
  source: 'all',
  search: '',
  limit: 150,
  sortBy: 'score',
};

let debounceTimer = null;

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  loadStats();
  loadSources();
  loadJobs();
});

function initEventListeners() {
  // Track tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.track = btn.dataset.track;
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
      showToast('Feed refreshed with latest data!');
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
}

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();
    
    document.getElementById('stat-total-jobs').textContent = data.total_jobs || '0';
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

    data.sources.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.name;
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
    <div style="text-align: center; padding: 3rem; color: var(--text-dim);">
      <div class="pulse-dot" style="margin: 0 auto 1rem auto; width: 12px; height: 12px;"></div>
      Scanning and ranking job postings...
    </div>
  `;

  const params = new URLSearchParams();
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
      countEl.innerHTML = `Showing <b>${data.count}</b> ranked job vacancies`;
    }

    if (!data.jobs || data.jobs.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <h3 class="empty-title">No matching jobs found</h3>
          <p class="empty-desc">Try loosening your track filter, searching for different keywords, or lowering the score threshold.</p>
          <button class="btn btn-ghost" onclick="resetFilters()">Reset All Filters</button>
        </div>
      `;
      return;
    }

    container.innerHTML = data.jobs.map((job, idx) => renderJobCard(job, idx)).join('');
  } catch (err) {
    console.error('Failed to load jobs:', err);
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <h3 class="empty-title">Error loading jobs</h3>
        <p class="empty-desc">Could not connect to the database API. Check backend service status.</p>
      </div>
    `;
  }
}

function renderJobCard(job, index) {
  const isMatch = job.final_score >= 9.0;
  const isNearMiss = !isMatch && job.final_score >= 6.5;

  let cardClass = 'job-card';
  if (isMatch) cardClass += ' is-match';
  else if (isNearMiss) cardClass += ' is-near-miss';

  let pillClass = 'score-pill low';
  let starIcon = '★';
  if (isMatch) {
    pillClass = 'score-pill match';
  } else if (isNearMiss) {
    pillClass = 'score-pill near-miss';
  }

  const trackClass = `track-tag ${job.best_track_id || 'general'}`;
  
  // Format breakdown chips
  const breakdown = job.breakdown || {};
  const chips = [];
  
  if (breakdown.tech_matches && breakdown.tech_matches.length > 0) {
    breakdown.tech_matches.slice(0, 4).forEach(k => {
      chips.push(`<span class="chip pos">+ ${escapeHtml(k)}</span>`);
    });
  }

  if (breakdown.location_bonus > 0) {
    chips.push(`<span class="chip loc">📍 +${breakdown.location_bonus.toFixed(1)} Location</span>`);
  }

  if (breakdown.seniority_bonus > 0) {
    chips.push(`<span class="chip pos">👔 +${breakdown.seniority_bonus.toFixed(1)} Seniority</span>`);
  }

  const postedText = job.first_seen ? formatRelativeTime(job.first_seen) : 'Recently';

  return `
    <div class="${cardClass}" id="job-card-${job.id}">
      <div class="job-top-bar">
        <div class="company-meta">
          <span class="company-name">${escapeHtml(job.company)}</span>
          <span class="source-badge">${escapeHtml(formatSourceName(job.source))}</span>
          <span class="posted-badge">Discovered ${postedText}</span>
        </div>
        <div class="${pillClass}">
          <span>${starIcon}</span>
          <span>${job.final_score.toFixed(1)}</span>
        </div>
      </div>

      <h3 class="job-title">${escapeHtml(job.title)}</h3>

      <div class="job-meta-row">
        <span class="meta-pill">📍 ${escapeHtml(job.location)}</span>
        <span class="${trackClass}">${escapeHtml(job.best_track_name || 'General')}</span>
      </div>

      <p class="job-snippet">${escapeHtml(job.description || '')}</p>

      ${chips.length > 0 ? `<div class="breakdown-chips">${chips.join('')}</div>` : ''}

      <div class="card-actions">
        <button class="btn btn-ghost" style="font-size: 0.8rem; padding: 0.4rem 0.8rem;" onclick="showBreakdownModal(${JSON.stringify(job).replace(/"/g, '&quot;')})">
          📊 Inspect Breakdown
        </button>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="apply-link">
          Apply on ${escapeHtml(formatSourceName(job.source))} ↗
        </a>
      </div>
    </div>
  `;
}

function showBreakdownModal(job) {
  const modal = document.getElementById('modal-overlay');
  const title = document.getElementById('modal-job-title');
  const content = document.getElementById('modal-job-content');
  if (!modal || !title || !content) return;

  const b = job.breakdown || {};
  title.textContent = `${job.title} (${job.company})`;

  content.innerHTML = `
    <div style="margin-bottom: 1.5rem;">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; padding: 1rem; background: rgba(255,255,255,0.03); border-radius: var(--radius-md);">
        <div>
          <div style="font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase;">Best Matched Track</div>
          <div style="font-size: 1.1rem; font-weight: 700; color: var(--accent-indigo);">${escapeHtml(b.best_track_name || 'General')}</div>
        </div>
        <div style="text-align: right;">
          <div style="font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase;">Final Score</div>
          <div style="font-size: 1.6rem; font-weight: 800; font-family: var(--font-mono); color: var(--accent-emerald);">${(b.final_score || job.final_score).toFixed(1)}</div>
        </div>
      </div>

      <h4 style="font-size: 0.9rem; margin-bottom: 0.5rem; color: var(--text-muted);">Scoring Calculation Breakdown:</h4>
      <div style="background: rgba(0,0,0,0.4); border: 1px solid var(--bg-card-border); border-radius: var(--radius-md); padding: 1rem; font-family: var(--font-mono); font-size: 0.825rem; line-height: 1.8;">
        <div>• Track Tech Score: <b style="color: #38bdf8;">+${(b.best_track_score || 0).toFixed(1)}</b></div>
        <div>• Location Bonus: <b style="color: var(--accent-emerald);">+${(b.location_bonus || 0).toFixed(1)}</b> (${escapeHtml(job.location)})</div>
        <div>• Seniority Bonus: <b style="color: var(--accent-emerald);">+${(b.seniority_bonus || 0).toFixed(1)}</b></div>
        <div>• Penalties Deducted: <b style="color: var(--accent-rose);">${(b.penalties || 0).toFixed(1)}</b></div>
      </div>

      <h4 style="font-size: 0.9rem; margin: 1.25rem 0 0.5rem 0; color: var(--text-muted);">Matched Keywords:</h4>
      <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
        ${(b.tech_matches || []).map(k => `<span class="chip pos" style="font-size: 0.8rem; padding: 0.25rem 0.65rem;">✓ ${escapeHtml(k)}</span>`).join('') || '<span style="color: var(--text-dim); font-size: 0.85rem;">None</span>'}
      </div>

      <div style="margin-top: 1.5rem; text-align: right;">
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary" style="display: inline-flex;">
          View Official Vacancy ↗
        </a>
      </div>
    </div>
  `;

  modal.classList.add('active');
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
      showToast(`Crawl completed! Checked ${data.summary.sources_checked} sources, found ${data.summary.matches_found} matches.`);
      loadStats();
      loadJobs();
    } else {
      showToast('Crawl encountered an issue: ' + (data.detail || 'Error'), true);
    }
  } catch (err) {
    showToast('Failed to trigger crawl.', true);
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

function showToast(message, isError = false) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }

  toast.style.borderColor = isError ? 'var(--accent-rose)' : 'var(--accent-emerald)';
  toast.innerHTML = `<span>${isError ? '⚠️' : '✅'}</span> <span>${escapeHtml(message)}</span>`;
  toast.classList.add('active');

  setTimeout(() => {
    toast.classList.remove('active');
  }, 4000);
}

function formatSourceName(sourceId) {
  if (!sourceId) return 'Direct';
  return sourceId
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatRelativeTime(isoString) {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffHours = Math.floor((now - date) / (1000 * 60 * 60));
    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
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
