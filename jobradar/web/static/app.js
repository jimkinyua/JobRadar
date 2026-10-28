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
  // Track tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.track = btn.dataset.track;

      // If user switches to a specific persona track, reset score filter to 'all'
      // so jobs matching the track are immediately visible!
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

    // Reset keeping only first option
    select.innerHTML = '<option value="all">🏢 All Sources</option>';

    data.sources.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = `${s.name} ${s.enabled ? '' : '(Disabled)'}`;
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

    currentJobs = {};
    data.jobs.forEach(j => {
      currentJobs[j.id] = j;
    });

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

function renderJobCard(job) {
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
  const fullDesc = job.full_description || job.description || 'No detailed requirements provided.';

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
        <div class="action-buttons-left">
          <button class="btn-toggle-req" id="btn-toggle-${job.id}" onclick="toggleRequirements(${job.id})">
            📋 View Requirements & Details <span class="req-arrow">▼</span>
          </button>
          <button class="btn-inspect" onclick="openJobModal(${job.id}, 'breakdown')">
            📊 Match Breakdown
          </button>
          ${job.breakdown?.ai_insight ? `
          <button class="btn-inspect" style="background: rgba(139, 92, 246, 0.1); border-color: rgba(139, 92, 246, 0.35); color: #7C3AED; font-weight: 700;" onclick="openJobModal(${job.id}, 'ai')">
            ✨ AI Fit (${job.breakdown.ai_insight.semantic_fit_score}%)
          </button>` : ''}
        </div>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="apply-link">
          Apply on ${escapeHtml(formatSourceName(job.source))} →
        </a>
      </div>

      <div class="job-req-drawer" id="req-drawer-${job.id}" style="display: none;">
        <div class="job-req-drawer-header">
          <span class="req-header-title">📋 Full Job Description & Role Requirements</span>
          <button class="btn-hide-req" onclick="toggleRequirements(${job.id})">Hide ▲</button>
        </div>
        <div class="req-drawer-body">
          ${formatDescriptionHtml(fullDesc)}
        </div>
        <div class="req-drawer-footer">
          <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary" style="font-size: 0.85rem; padding: 0.45rem 1rem;">
            Apply Directly on ${escapeHtml(formatSourceName(job.source))} →
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
    btn.innerHTML = `📋 View Requirements & Details <span class="req-arrow">▼</span>`;
  } else {
    drawer.style.display = 'block';
    btn.classList.add('open');
    btn.innerHTML = `📋 Hide Requirements & Details <span class="req-arrow">▲</span>`;
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

  content.innerHTML = `
    <div class="modal-nav-tabs">
      <button class="modal-nav-btn ${initialTab === 'requirements' ? 'active' : ''}" id="modal-tab-req" onclick="switchModalTab('requirements')">
        📋 Full Requirements
      </button>
      <button class="modal-nav-btn ${initialTab === 'breakdown' ? 'active' : ''}" id="modal-tab-score" onclick="switchModalTab('breakdown')">
        📊 Scoring Breakdown
      </button>
      ${job.breakdown?.ai_insight ? `
      <button class="modal-nav-btn ${initialTab === 'ai' ? 'active' : ''}" id="modal-tab-ai" onclick="switchModalTab('ai')" style="background: rgba(139, 92, 246, 0.1); border-color: rgba(139, 92, 246, 0.4); color: #7C3AED; font-weight: 700;">
        ✨ AI Career Copilot (${job.breakdown.ai_insight.semantic_fit_score}%)
      </button>` : ''}
    </div>

    <div id="modal-pane-requirements" style="display: ${initialTab === 'requirements' ? 'block' : 'none'};">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; padding: 0.85rem 1.1rem; background: var(--bg-subtle); border-radius: var(--radius-md);">
        <div>
          <span style="font-size: 0.85rem; color: var(--text-muted);">Source: <b>${escapeHtml(formatSourceName(job.source))}</b></span>
          <span style="margin: 0 0.5rem; color: var(--border-light);">|</span>
          <span style="font-size: 0.85rem; color: var(--text-muted);">Location: <b>${escapeHtml(job.location)}</b></span>
        </div>
        <span class="track-tag ${job.best_track_id || 'general'}">${escapeHtml(job.best_track_name || 'General')}</span>
      </div>

      <div class="req-drawer-body" style="max-height: 52vh; padding-right: 0.75rem;">
        ${formatDescriptionHtml(job.full_description || job.description)}
      </div>

      <div style="margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 1rem; border-top: 1px solid var(--border-light);">
        <button class="btn btn-ghost" onclick="switchModalTab('breakdown')">View Score Breakdown 📊</button>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
          Apply on ${escapeHtml(formatSourceName(job.source))} →
        </a>
      </div>
    </div>

    <div id="modal-pane-breakdown" style="display: ${initialTab === 'breakdown' ? 'block' : 'none'};">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; padding: 1.2rem; background: var(--bg-subtle); border-radius: var(--radius-lg); border: 1px solid var(--border-light);">
        <div>
          <div style="font-family: var(--font-mono); font-size: 0.725rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;">Best Matched Persona Track</div>
          <div style="font-size: 1.15rem; font-weight: 800; color: var(--text-headline);">${escapeHtml(job.best_track_name || 'General')}</div>
        </div>
        <div style="text-align: right;">
          <div style="font-family: var(--font-mono); font-size: 0.725rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;">Match Score</div>
          <div style="font-size: 1.75rem; font-weight: 800; font-family: var(--font-mono); color: var(--brand-green);">${job.final_score.toFixed(1)}</div>
        </div>
      </div>

      <h4 style="font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.6rem; color: var(--text-muted);">Scoring Formula:</h4>
      <div style="background: #FFFFFF; border: 1.5px solid var(--border-light); border-radius: var(--radius-md); padding: 1.1rem; font-family: var(--font-mono); font-size: 0.85rem; line-height: 2;">
        <div>• Track Tech Score: <b style="color: var(--brand-green);">+${(job.breakdown?.best_track_score || 0).toFixed(1)}</b></div>
        <div>• Location Bonus: <b style="color: var(--brand-green);">+${(job.breakdown?.location_bonus || 0).toFixed(1)}</b> (${escapeHtml(job.location)})</div>
        <div>• Seniority Bonus: <b style="color: var(--brand-green);">+${(job.breakdown?.seniority_bonus || 0).toFixed(1)}</b></div>
        <div>• Penalties Deducted: <b style="color: #DC2626;">-${(job.breakdown?.penalties || 0).toFixed(1)}</b></div>
      </div>

      <h4 style="font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin: 1.25rem 0 0.6rem 0; color: var(--text-muted);">Matched Track Keywords:</h4>
      <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
        ${(job.breakdown?.tech_matches || []).map(k => `<span class="chip pos" style="font-size: 0.825rem; padding: 0.35rem 0.75rem;">✓ ${escapeHtml(k)}</span>`).join('') || '<span style="color: var(--text-dim); font-size: 0.85rem;">None</span>'}
      </div>

      <div style="margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 1rem; border-top: 1px solid var(--border-light);">
        <button class="btn btn-ghost" onclick="switchModalTab('requirements')">← Read Full Requirements</button>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
          View Official Vacancy →
        </a>
      </div>
    </div>

    <div id="modal-pane-ai" style="display: ${initialTab === 'ai' ? 'block' : 'none'};">
      ${job.breakdown?.ai_insight ? `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; padding: 1.2rem; background: linear-gradient(135deg, rgba(139, 92, 246, 0.08), rgba(59, 130, 246, 0.05)); border-radius: var(--radius-lg); border: 1px solid rgba(139, 92, 246, 0.25);">
        <div>
          <div style="font-family: var(--font-mono); font-size: 0.725rem; font-weight: 700; color: #7C3AED; text-transform: uppercase; letter-spacing: 0.05em;">AI Semantic Persona Match</div>
          <div style="font-size: 1.15rem; font-weight: 800; color: var(--text-headline);">Candidate Profile Alignment</div>
        </div>
        <div style="text-align: right;">
          <div style="font-family: var(--font-mono); font-size: 0.725rem; font-weight: 700; color: #7C3AED; text-transform: uppercase; letter-spacing: 0.05em;">Fit Score</div>
          <div style="font-size: 1.85rem; font-weight: 800; font-family: var(--font-mono); color: #7C3AED;">${job.breakdown.ai_insight.semantic_fit_score}%</div>
        </div>
      </div>

      <div style="margin-bottom: 1.25rem;">
        <h4 style="font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; color: var(--text-muted);">💡 Why You Match:</h4>
        <div style="background: var(--bg-card); border: 1px solid var(--border-light); border-radius: var(--radius-md); padding: 1rem; font-size: 0.9rem; line-height: 1.6; color: var(--text-headline);">
          ${escapeHtml(job.breakdown.ai_insight.fit_rationale)}
        </div>
      </div>

      ${(job.breakdown.ai_insight.skill_gaps || []).length > 0 ? `
      <div style="margin-bottom: 1.25rem;">
        <h4 style="font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; color: #DC2626;">⚠️ Skill Gaps to Prepare:</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
          ${job.breakdown.ai_insight.skill_gaps.map(g => `<span class="chip neg" style="font-size: 0.8rem; padding: 0.35rem 0.65rem;">${escapeHtml(g)}</span>`).join('')}
        </div>
      </div>` : ''}

      ${job.breakdown.ai_insight.tailored_pitch ? `
      <div style="margin-bottom: 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
          <h4 style="font-family: var(--font-mono); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted);">🚀 Tailored CV / Cover Letter Pitch:</h4>
          <button id="copy-pitch-btn" class="btn btn-ghost" style="font-size: 0.75rem; padding: 0.25rem 0.6rem;" onclick="copyTailoredPitch(${job.id})">📋 Copy Pitch</button>
        </div>
        <div id="pitch-text-${job.id}" style="background: #F8FAFC; border: 1.5px dashed rgba(139, 92, 246, 0.4); border-radius: var(--radius-md); padding: 1.1rem; font-style: italic; font-size: 0.875rem; line-height: 1.6; color: var(--text-headline);">
          "${escapeHtml(job.breakdown.ai_insight.tailored_pitch)}"
        </div>
      </div>` : ''}
      ` : `
      <div class="empty-state" style="padding: 2rem;">
        <div class="empty-icon">🤖</div>
        <h4 class="empty-title">AI Insight Not Generated Yet</h4>
        <p class="empty-desc">This job has not been evaluated by Gemini AI yet.</p>
      </div>
      `}

      <div style="margin-top: 1.5rem; display: flex; justify-content: flex-end; gap: 0.75rem; padding-top: 1rem; border-top: 1px solid var(--border-light);">
        <button class="btn btn-ghost" onclick="switchModalTab('requirements')">← Read Full Requirements</button>
        <a href="${escapeHtml(job.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
          View Official Vacancy →
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
  if (!pitchElem) return;
  const text = pitchElem.innerText.replace(/^"|"$/g, '').trim();
  navigator.clipboard.writeText(text).then(() => {
    showToast('🚀 Tailored pitch copied to clipboard!');
  });
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
      showToast(`Crawl completed! Checked ${checked} sources, found ${matches} matches.`);
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

function formatDescriptionHtml(text) {
  if (!text) return '<p style="color: var(--text-dim);">No detailed description provided.</p>';
  
  // If text already contains HTML paragraph/list tags
  if (/<[a-z][\s\S]*>/i.test(text)) {
    // Basic sanitization: strip script/iframe tags
    let clean = text
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
      .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
      .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '');
    return clean;
  }

  // Convert plain text with newlines and bullets into clean semantic HTML
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

    // Check for bullet points
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
    'coop_bank': 'Co-op Bank',
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
  toast.style.borderColor = isError ? '#EF4444' : 'var(--brand-green)';
  toast.classList.add('active');

  setTimeout(() => {
    toast.classList.remove('active');
  }, 4000);
}
