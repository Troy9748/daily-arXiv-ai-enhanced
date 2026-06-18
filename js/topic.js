const params = new URLSearchParams(location.search);
const topicName = params.get('topic') || 'Other Selected Research';
const topicScope = params.get('scope') === 'all' ? 'all' : 'year';
let topicPapers = [];

document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('topicTitle').textContent = topicName;
  document.getElementById('topicSearch').addEventListener('input', renderTopicPapers);
  document.getElementById('topicSort').addEventListener('change', renderTopicPapers);
  document.getElementById('saveTopicButton').addEventListener('click', toggleSavedTopic);
  refreshSavedTopicButton();
  try {
    const response = await fetch(`data/statistics_${topicScope}.json`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    topicPapers = payload.papers.filter(paper => (paper.topics || []).includes(topicName));
    document.getElementById('topicSummary').textContent = `${topicPapers.length} papers · ${topicScope === 'year' ? 'recent year' : 'all library'}`;
    renderTopicPapers();
  } catch (error) {
    document.getElementById('topicPapers').innerHTML = '<p class="statistics-error">Unable to load topic data.</p>';
  }
});

function savedTopics() {
  try { return JSON.parse(localStorage.getItem('dailyArxivSavedTopics') || '[]'); }
  catch (error) { return []; }
}

function toggleSavedTopic() {
  const topics = savedTopics();
  const next = topics.includes(topicName) ? topics.filter(topic => topic !== topicName) : [...topics, topicName];
  localStorage.setItem('dailyArxivSavedTopics', JSON.stringify(next));
  refreshSavedTopicButton();
}

function refreshSavedTopicButton() {
  const saved = savedTopics().includes(topicName);
  const button = document.getElementById('saveTopicButton');
  button.textContent = saved ? 'Saved' : 'Save topic';
  button.classList.toggle('active', saved);
}

function renderTopicPapers() {
  const query = document.getElementById('topicSearch').value.trim().toLowerCase();
  const sort = document.getElementById('topicSort').value;
  const papers = topicPapers.filter(paper => `${paper.title} ${paper.summary} ${(paper.authors || []).join(' ')}`.toLowerCase().includes(query));
  papers.sort((a, b) => sort === 'date' ? b.date.localeCompare(a.date) : (b.score - a.score || b.date.localeCompare(a.date)));
  document.getElementById('topicPapers').innerHTML = papers.map(paper => `
    <article class="topic-paper-card">
      <div class="topic-paper-score"><strong>${paper.score}</strong><span>/100</span></div>
      <div class="topic-paper-body">
        <div class="topic-paper-badges">${paper.mandatory ? '<span class="must-read-badge">Must read</span>' : ''}${paper.version_count > 1 ? `<span class="version-badge">Updated · ${paper.version_count} versions</span>` : ''}</div>
        <h2><button type="button" class="paper-detail-title" data-paper-detail="${escapeTopicHtml(paper.id)}">${escapeTopicHtml(paper.title)}</button></h2>
        <p class="topic-paper-authors">${escapeTopicHtml((paper.authors || []).join(', '))}</p>
        <p>${escapeTopicHtml(paper.summary || '')}</p>
        <div class="topic-paper-footer"><span>${paper.date}</span><span>${(paper.categories || []).join(', ')}</span></div>
      </div>
    </article>`).join('') || '<p>No matching papers.</p>';
  window.PaperDetail?.bind(document.getElementById('topicPapers'), papers);
}

function escapeTopicHtml(value) {
  return String(value || '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'})[character]);
}
