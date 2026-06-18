(function () {
  const cache = new Map();

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>'"]/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;'
    })[character]);
  }

  function formatAcademic(value) {
    const escaped = escapeHtml(value);
    if (/\\\(|\\\)|\$/.test(String(value || ''))) return escaped;
    return escaped
      .replace(/_\{([^{}]+)\}/g, '<sub>$1</sub>')
      .replace(/\^\{([^{}]+)\}/g, '<sup>$1</sup>')
      .replace(/_([A-Za-z0-9.]+)/g, '<sub>$1</sub>')
      .replace(/\^([A-Za-z0-9.+-]+)/g, '<sup>$1</sup>');
  }

  function ensureModal() {
    let modal = document.getElementById('libraryPaperModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'libraryPaperModal';
    modal.className = 'library-paper-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = '<div class="library-paper-dialog"><button class="library-paper-close" type="button" aria-label="Close">&times;</button><div id="libraryPaperModalBody"></div></div>';
    document.body.appendChild(modal);
    modal.querySelector('.library-paper-close').addEventListener('click', close);
    modal.addEventListener('click', event => { if (event.target === modal) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && modal.classList.contains('active')) close(); });
    return modal;
  }

  async function fetchFullPaper(paper) {
    const key = `${paper.date}:${paper.id}`;
    if (cache.has(key)) return cache.get(key);
    for (const language of ['Chinese', 'English']) {
      try {
        const response = await fetch(`data/${paper.date}_AI_enhanced_${language}.jsonl`, { cache: 'no-store' });
        if (!response.ok) continue;
        const rows = (await response.text()).split('\n').filter(Boolean).map(line => JSON.parse(line));
        const found = rows.find(row => String(row.id).replace(/v\d+$/, '') === String(paper.id).replace(/v\d+$/, ''));
        if (found) {
          cache.set(key, found);
          return found;
        }
      } catch (error) {
        console.warn('Paper detail source unavailable:', error);
      }
    }
    cache.set(key, paper);
    return paper;
  }

  function breakdownHtml(entries) {
    if (!Array.isArray(entries) || !entries.length) return '';
    return `<div class="score-breakdown">${entries.map(entry => {
      const points = Number(entry.points || 0);
      return `<span class="score-breakdown-item ${points >= 0 ? 'positive' : 'negative'}">${points >= 0 ? '+' : ''}${points} ${escapeHtml(entry.label)}</span>`;
    }).join('')}</div>`;
  }

  function figuresHtml(figures) {
    if (!Array.isArray(figures) || !figures.length) return '';
    return `<details class="library-paper-section" open><summary>重点图片</summary><div class="library-figure-grid">${figures.map((figure, index) => {
      const imageUrl = escapeHtml(figure.image_url || '');
      return `<figure>${imageUrl ? `<a href="${imageUrl}" target="_blank" rel="noopener"><img src="${imageUrl}" alt="${escapeHtml(figure.figure_label || `Figure ${index + 1}`)}" loading="lazy"></a>` : ''}<figcaption>${formatAcademic(figure.caption_zh || figure.caption_en || '')}</figcaption></figure>`;
    }).join('')}</div></details>`;
  }

  async function open(compactPaper) {
    const modal = ensureModal();
    const body = modal.querySelector('#libraryPaperModalBody');
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    body.innerHTML = '<div class="statistics-loading">Loading paper details...</div>';
    const paper = await fetchFullPaper(compactPaper);
    const ai = paper.AI || {};
    const artifacts = paper.artifacts || {};
    const recommendation = paper.recommendation || compactPaper;
    const mandatory = Boolean(compactPaper.mandatory);
    const score = mandatory
      ? Math.max(92, Number(recommendation.score || compactPaper.score || 0))
      : Number(recommendation.score || compactPaper.score || 0);
    const reason = compactPaper.must_read_reason || recommendation.reason || '';
    body.innerHTML = `
      <div class="library-paper-heading">
        <div class="library-paper-score"><strong>${score}</strong><span>/100</span></div>
        <div><div class="topic-paper-badges">${mandatory ? `<span class="must-read-badge" title="${escapeHtml(reason)}">Must read · ${escapeHtml(reason)}</span>` : ''}</div><h1>${formatAcademic(paper.title || compactPaper.title)}</h1><p>${escapeHtml((paper.authors || compactPaper.authors || []).join ? (paper.authors || compactPaper.authors).join(', ') : paper.authors)}</p></div>
      </div>
      ${breakdownHtml(recommendation.score_breakdown || compactPaper.score_breakdown)}
      <div class="library-paper-links"><a href="${escapeHtml(paper.abs || compactPaper.url)}" target="_blank" rel="noopener">arXiv</a><a href="${escapeHtml(paper.pdf || String(paper.abs || compactPaper.url).replace('/abs/', '/pdf/'))}" target="_blank" rel="noopener">PDF</a></div>
      ${ai.tldr || compactPaper.summary ? `<section class="library-paper-section"><h2>TL;DR</h2><p>${formatAcademic(ai.tldr || compactPaper.summary)}</p></section>` : ''}
      <div class="library-paper-section-grid">
        ${ai.motivation ? `<section class="library-paper-section"><h2>Motivation</h2><p>${formatAcademic(ai.motivation)}</p></section>` : ''}
        ${ai.method ? `<section class="library-paper-section"><h2>Method</h2><p>${formatAcademic(ai.method)}</p></section>` : ''}
        ${ai.result ? `<section class="library-paper-section"><h2>Result</h2><p>${formatAcademic(ai.result)}</p></section>` : ''}
        ${ai.conclusion ? `<section class="library-paper-section"><h2>Conclusion</h2><p>${formatAcademic(ai.conclusion)}</p></section>` : ''}
      </div>
      ${paper.summary ? `<details class="library-paper-section"><summary>Abstract</summary><p>${formatAcademic(paper.summary)}</p></details>` : ''}
      ${artifacts.abstract_zh ? `<details class="library-paper-section"><summary>摘要翻译</summary><p>${formatAcademic(artifacts.abstract_zh)}</p></details>` : ''}
      ${artifacts.conclusion_zh ? `<details class="library-paper-section"><summary>结论翻译</summary><p>${formatAcademic(artifacts.conclusion_zh)}</p></details>` : ''}
      ${figuresHtml(artifacts.figures)}
      ${paper === compactPaper ? '<p class="library-paper-archive-note">该论文位于低成本归档，未执行 AI 摘要、翻译和图注处理。</p>' : ''}
    `;
    if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
      window.MathJax.typesetPromise([body]).catch(error => console.warn('Math rendering failed:', error));
    }
  }

  function close() {
    const modal = document.getElementById('libraryPaperModal');
    if (!modal) return;
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function bind(container, papers) {
    const map = new Map((papers || []).map(paper => [String(paper.id), paper]));
    container.querySelectorAll('[data-paper-detail]').forEach(button => {
      button.addEventListener('click', () => {
        const paper = map.get(String(button.dataset.paperDetail));
        if (paper) open(paper);
      });
    });
  }

  window.PaperDetail = { bind, open, close };
})();
