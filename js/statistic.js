let statisticsScope = localStorage.getItem('dailyArxivStatisticsScope') || 'year';
let statisticsPayload = null;
let weeklyDigest = null;

document.addEventListener('DOMContentLoaded', () => {
  initStatistics();
  fetchGitHubStats();
});

async function fetchGitHubStats() {
  try {
    const response = await fetch('https://api.github.com/repos/Troy9748/daily-arXiv-ai-enhanced');
    if (!response.ok) return;
    const data = await response.json();
    const star = document.getElementById('starCount');
    const fork = document.getElementById('forkCount');
    if (star) star.textContent = data.stargazers_count;
    if (fork) fork.textContent = data.forks_count;
  } catch (error) {
    console.warn('GitHub statistics unavailable:', error);
  }
}

async function initStatistics() {
  document.querySelectorAll('[data-stat-scope]').forEach(button => {
    button.addEventListener('click', () => loadStatistics(button.dataset.statScope));
  });
  await loadStatistics(statisticsScope);
}

async function loadStatistics(scope) {
  statisticsScope = scope === 'all' ? 'all' : 'year';
  localStorage.setItem('dailyArxivStatisticsScope', statisticsScope);
  document.querySelectorAll('[data-stat-scope]').forEach(button => {
    button.classList.toggle('active', button.dataset.statScope === statisticsScope);
  });
  const container = document.getElementById('papersList');
  container.innerHTML = '<div class="statistics-loading">Loading research library statistics...</div>';
  try {
    const [response, weeklyResponse] = await Promise.all([
      fetch(`data/statistics_${statisticsScope}.json`, { cache: 'no-store' }),
      fetch('data/weekly_digest.json', { cache: 'no-store' })
    ]);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    statisticsPayload = await response.json();
    weeklyDigest = weeklyResponse.ok ? await weeklyResponse.json() : null;
    renderStatistics(statisticsPayload);
  } catch (error) {
    container.innerHTML = `<div class="statistics-error">Statistics data is not available yet. Run <code>python ai/generate_statistics.py</code>.</div>`;
  }
}

function topicUrl(topic) {
  const params = new URLSearchParams({ topic, scope: statisticsScope });
  return `topic.html?${params.toString()}`;
}

function renderStatistics(payload) {
  const reports = payload.selection_reports || [];
  const latestReport = reports[0] || {};
  const mustRead = payload.papers.filter(paper => paper.mandatory).length;
  const updated = payload.papers.filter(paper => Number(paper.version_count || 1) > 1).length;
  const topPapers = payload.papers.slice(0, 10);
  const saved = savedResearchTopics();
  document.getElementById('currentDate').textContent = statisticsScope === 'year' ? 'Recent year' : 'All library';
  document.getElementById('papersList').innerHTML = `
    <section class="statistics-summary-grid">
      ${summaryCard('Library papers', payload.paper_count)}
      ${summaryCard('Must-read lensing', mustRead)}
      ${summaryCard('Version updates', updated)}
      ${summaryCard('Latest AI calls saved', latestReport.estimated_ai_calls_saved || 0)}
    </section>
    <section class="statistics-section archive-callout"><div><h2>Low-cost Candidate Archive</h2><p>Search papers excluded before AI enhancement. Nothing is permanently discarded.</p></div><a class="save-topic-button active" href="archive.html">Open archive</a></section>
    <section class="statistics-section">
      <div class="statistics-section-heading">
        <div><h2>Research Topics</h2><p>Stable scientific categories, not generic word frequency.</p></div>
      </div>
      <div class="research-topic-grid">
        ${payload.topics.map(topic => `
          <a class="research-topic-card" href="${topicUrl(topic.name)}">
            <span>${escapeHtml(topic.name)}</span><strong>${topic.count}</strong>
          </a>
        `).join('')}
      </div>
    </section>
    ${saved.length ? `<section class="statistics-section"><div class="statistics-section-heading"><div><h2>Saved Topics</h2><p>Your persistent research watches.</p></div></div><div class="research-topic-grid">${saved.map(topic => `<a class="research-topic-card" href="${topicUrl(topic)}"><span>${escapeHtml(topic)}</span><strong>Open</strong></a>`).join('')}</div></section>` : ''}
    ${weeklyDigest && weeklyDigest.papers && weeklyDigest.papers.length ? `<section class="statistics-section"><div class="statistics-section-heading"><div><h2>Weekly Digest</h2><p>Top 10 papers from the latest seven days.</p></div></div><div class="statistics-paper-list">${weeklyDigest.papers.slice(0, 10).map(renderStatisticsPaper).join('')}</div></section>` : ''}
    <section class="statistics-section">
      <div class="statistics-section-heading"><div><h2>Highest Priority</h2><p>Mandatory papers first, then recommendation score.</p></div></div>
      <div class="statistics-paper-list">${topPapers.map(renderStatisticsPaper).join('')}</div>
    </section>
    ${latestReport.generated_at ? `
      <section class="statistics-section selection-report">
        <div class="statistics-section-heading"><div><h2>Latest Selection Report</h2><p>${escapeHtml(latestReport.date || '')}</p></div></div>
        <div class="selection-report-row">
          <span>Crawled <strong>${latestReport.input_count}</strong></span>
          <span>Selected <strong>${latestReport.selected_count}</strong></span>
          <span>Archived <strong>${latestReport.archived_count}</strong></span>
          <span>Mandatory <strong>${latestReport.mandatory_count}</strong></span>
        </div>
      </section>` : ''}
  `;
  const detailPapers = [...payload.papers, ...((weeklyDigest && weeklyDigest.papers) || [])];
  window.PaperDetail?.bind(document.getElementById('papersList'), detailPapers);
}

function savedResearchTopics() {
  try { return JSON.parse(localStorage.getItem('dailyArxivSavedTopics') || '[]'); }
  catch (error) { return []; }
}

function summaryCard(label, value) {
  return `<div class="statistics-summary-card"><strong>${value}</strong><span>${label}</span></div>`;
}

function renderStatisticsPaper(paper) {
  const tier = paper.mandatory ? '<span class="must-read-badge">Must read</span>' : '';
  const version = Number(paper.version_count || 1) > 1 ? `<span class="version-badge">${paper.version_count} versions</span>` : '';
  return `<article class="statistics-paper-card">
    <div class="statistics-paper-score">${paper.score}</div>
    <div><h3><button type="button" class="paper-detail-title" data-paper-detail="${escapeHtml(paper.id)}">${escapeHtml(paper.title)}</button></h3>
      <div class="statistics-paper-meta">${tier}${version}<span>${escapeHtml(paper.date)}</span></div>
      <p>${escapeHtml(paper.summary || '')}</p>
    </div>
  </article>`;
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;'
  })[character]);
}
