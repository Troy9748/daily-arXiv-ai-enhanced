let archivePapers = [];
document.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('archiveSearch').addEventListener('input', renderArchive);
  document.getElementById('archiveSort').addEventListener('change', renderArchive);
  try {
    const response = await fetch('data/archive_index.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    archivePapers = payload.papers || [];
    document.getElementById('archiveSummary').textContent = `${archivePapers.length} papers kept without expensive AI enhancement`;
    renderArchive();
  } catch (error) {
    document.getElementById('archivePapers').innerHTML = '<p class="statistics-error">Archive data is not available yet.</p>';
  }
});

function renderArchive() {
  const query = document.getElementById('archiveSearch').value.trim().toLowerCase();
  const sort = document.getElementById('archiveSort').value;
  const rows = archivePapers.filter(paper => `${paper.title} ${paper.summary} ${(paper.authors || []).join(' ')}`.toLowerCase().includes(query));
  rows.sort((a, b) => sort === 'date' ? b.date.localeCompare(a.date) : (b.score - a.score || b.date.localeCompare(a.date)));
  const visibleRows = rows.slice(0, 300);
  document.getElementById('archivePapers').innerHTML = visibleRows.map(paper => `<article class="topic-paper-card"><div class="topic-paper-score"><strong>${paper.score}</strong><span>pre-score</span></div><div class="topic-paper-body"><h2><button type="button" class="paper-detail-title" data-paper-detail="${escapeArchive(paper.id)}">${escapeArchive(paper.title)}</button></h2><p class="topic-paper-authors">${escapeArchive((paper.authors || []).join(', '))}</p><p>${escapeArchive(paper.summary || '')}</p><div class="topic-paper-footer"><span>${paper.date}</span><span>Not AI enhanced</span></div></div></article>`).join('') || '<p>No matching archived papers.</p>';
  window.PaperDetail?.bind(document.getElementById('archivePapers'), visibleRows);
}

function escapeArchive(value) { return String(value || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'})[c]); }
