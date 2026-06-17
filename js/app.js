let currentDate = '';
let availableDates = [];
let currentView = 'grid'; // 'grid' 或 'list'
let currentCategory = 'all';
let paperData = {};
let flatpickrInstance = null;
let isRangeMode = false;
let activeKeywords = []; // 存储激活的关键词
let userKeywords = []; // 存储用户的关键词
let activeAuthors = []; // 存储激活的作者
let userAuthors = []; // 存储用户的作者
let currentPaperIndex = 0; // 当前查看的论文索引
let currentFilteredPapers = []; // 当前过滤后的论文列表
let textSearchQuery = ''; // 实时文本搜索查询
let previousActiveKeywords = null; // 文本搜索激活时，暂存之前的关键词激活集合
let previousActiveAuthors = null; // 文本搜索激活时，暂存之前的作者激活集合
let isTop100Mode = false; // 标记当前是否处于历史高分推荐模式
let currentTopListMode = null; // 'year' | 'month' | 'week'

const TOP_LISTS = {
  year: {
    label: '近一年 Top 100',
    shortLabel: 'Year 100',
    file: 'top_year_100_AI_enhanced.jsonl'
  },
  month: {
    label: '近一月 Top 20',
    shortLabel: 'Month 20',
    file: 'top_month_20_AI_enhanced.jsonl'
  },
  week: {
    label: '近一周 Top 10',
    shortLabel: 'Week 10',
    file: 'top_week_10_AI_enhanced.jsonl'
  }
};

const LIKED_PAPERS_KEY = 'dailyArxivLikedPapers';
const ZOTERO_CONFIG_KEY = 'dailyArxivZoteroConfig';

function getRecommendationScore(paper) {
  return paper && paper.recommendation ? Number(paper.recommendation.score || 0) : 0;
}

function renderStars(stars) {
  const filled = Math.max(1, Math.min(5, Number(stars || 1)));
  return `${'★'.repeat(filled)}${'☆'.repeat(5 - filled)}`;
}

function compareByRecommendation(a, b) {
  return getRecommendationScore(b) - getRecommendationScore(a);
}

function getLikedPapers() {
  try {
    return JSON.parse(localStorage.getItem(LIKED_PAPERS_KEY) || '[]');
  } catch (error) {
    console.error('读取点赞论文失败:', error);
    return [];
  }
}

function saveLikedPapers(papers) {
  localStorage.setItem(LIKED_PAPERS_KEY, JSON.stringify(papers));
}

function paperLikeId(paper) {
  return paper && (paper.id || paper.url || paper.title);
}

function isPaperLiked(paper) {
  const id = paperLikeId(paper);
  return Boolean(id && getLikedPapers().some(item => paperLikeId(item) === id));
}

function paperToLikedPayload(paper) {
  return {
    id: paper.id,
    title: paper.title,
    url: paper.url,
    pdf: paper.url ? paper.url.replace('abs', 'pdf') : '',
    authors: Array.isArray(paper.authors) ? paper.authors : String(paper.authors || '').split(',').map(v => v.trim()).filter(Boolean),
    category: paper.category,
    summary: paper.summary,
    details: paper.details,
    date: paper.date,
    liked_at: new Date().toISOString()
  };
}

function updateLikeButton(paper) {
  const button = document.getElementById('likePaperButton');
  if (!button) return;
  const liked = isPaperLiked(paper);
  button.classList.toggle('liked', liked);
  button.title = liked ? 'Unlike paper' : 'Like paper';
}

function toggleCurrentPaperLike() {
  const paper = currentFilteredPapers[currentPaperIndex];
  if (!paper) return;
  const id = paperLikeId(paper);
  const liked = getLikedPapers();
  const existing = liked.findIndex(item => paperLikeId(item) === id);
  if (existing >= 0) {
    liked.splice(existing, 1);
  } else {
    liked.unshift(paperToLikedPayload(paper));
  }
  saveLikedPapers(liked);
  updateLikeButton(paper);
}

function exportLikedPapers() {
  const payload = {
    version: 1,
    exported_at: new Date().toISOString(),
    papers: getLikedPapers()
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'liked_papers.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function getZoteroConfig() {
  try {
    return JSON.parse(localStorage.getItem(ZOTERO_CONFIG_KEY) || '{}');
  } catch (error) {
    return {};
  }
}

function promptZoteroConfig() {
  const current = getZoteroConfig();
  const apiKey = prompt('Zotero API Key（只保存在本浏览器 localStorage）', current.apiKey || '');
  if (!apiKey) return null;
  const libraryType = prompt('Zotero library type: users 或 groups', current.libraryType || 'users') || 'users';
  const libraryId = prompt('Zotero user ID 或 group ID', current.libraryId || '');
  if (!libraryId) return null;
  const collectionKey = prompt('daily_arxiv collection key（可留空则保存到库根目录）', current.collectionKey || '') || '';
  const config = { apiKey, libraryType, libraryId, collectionKey };
  localStorage.setItem(ZOTERO_CONFIG_KEY, JSON.stringify(config));
  return config;
}

function zoteroCreators(authors) {
  return String(authors || '').split(',').map(name => name.trim()).filter(Boolean).map(name => ({
    creatorType: 'author',
    name
  }));
}

function normalizeFigureImageUrl(url) {
  const value = String(url || '');
  const match = value.match(/^https:\/\/arxiv\.org\/(\d{4}\.\d+(?:v\d+)?)\/(.+)$/);
  if (match) {
    return `https://arxiv.org/html/${match[1]}/${match[2]}`;
  }
  return value;
}

async function addCurrentPaperToZotero() {
  const paper = currentFilteredPapers[currentPaperIndex];
  if (!paper) return;
  let config = getZoteroConfig();
  if (!config.apiKey || !config.libraryId) {
    config = promptZoteroConfig();
  }
  if (!config) return;

  const item = {
    itemType: 'journalArticle',
    title: paper.title || '',
    creators: zoteroCreators(paper.authors),
    abstractNote: paper.details || paper.summary || '',
    url: paper.url || '',
    publicationTitle: 'arXiv',
    archive: 'arXiv',
    archiveLocation: paper.id || '',
    extra: `arXiv: ${paper.id || ''}\nDaily arXiv score: ${getRecommendationScore(paper)}/100`,
    tags: [
      { tag: 'daily_arxiv' },
      { tag: 'arXiv' }
    ]
  };
  if (config.collectionKey) {
    item.collections = [config.collectionKey];
  }

  const endpoint = `https://api.zotero.org/${config.libraryType || 'users'}/${config.libraryId}/items`;
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Zotero-API-Key': config.apiKey
      },
      body: JSON.stringify([item])
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status}: ${text}`);
    }
    alert('已添加到 Zotero。');
  } catch (error) {
    console.error('添加 Zotero 失败:', error);
    alert(`添加 Zotero 失败：${error.message}`);
  }
}

// 加载用户的关键词设置
function loadUserKeywords() {
  const savedKeywords = localStorage.getItem('preferredKeywords');
  if (savedKeywords) {
    try {
      userKeywords = JSON.parse(savedKeywords);
      // 默认激活所有关键词
      activeKeywords = [...userKeywords];
    } catch (error) {
      console.error('解析关键词失败:', error);
      userKeywords = [];
      activeKeywords = [];
    }
  } else {
    userKeywords = [];
    activeKeywords = [];
  }
  
  renderFilterTags();
}

// 加载用户的作者设置
function loadUserAuthors() {
  const savedAuthors = localStorage.getItem('preferredAuthors');
  if (savedAuthors) {
    try {
      userAuthors = JSON.parse(savedAuthors);
      // 默认激活所有作者
      activeAuthors = [...userAuthors];
    } catch (error) {
      console.error('解析作者失败:', error);
      userAuthors = [];
      activeAuthors = [];
    }
  } else {
    userAuthors = [];
    activeAuthors = [];
  }
  
  renderFilterTags();
}

// 渲染过滤标签（作者和关键词）
function renderFilterTags() {
  const filterTagsElement = document.getElementById('filterTags');
  const filterContainer = document.querySelector('.filter-label-container');
  
  if ((!userAuthors || userAuthors.length === 0) && (!userKeywords || userKeywords.length === 0)) {
    filterContainer.style.display = 'flex';
    if (filterTagsElement) {
      filterTagsElement.style.display = 'none';
      filterTagsElement.innerHTML = '';
    }
    return;
  }
  
  filterContainer.style.display = 'flex';
  if (filterTagsElement) {
    filterTagsElement.style.display = 'flex';
  }
  filterTagsElement.innerHTML = '';
  
  if (userAuthors && userAuthors.length > 0) {
    userAuthors.forEach(author => {
      const tagElement = document.createElement('span');
      tagElement.className = `category-button author-button ${activeAuthors.includes(author) ? 'active' : ''}`;
      tagElement.textContent = author;
      tagElement.dataset.author = author;
      tagElement.title = "匹配作者姓名";
      
      tagElement.addEventListener('click', () => {
        toggleAuthorFilter(author);
      });
      
      filterTagsElement.appendChild(tagElement);
      
      if (!activeAuthors.includes(author)) {
        tagElement.classList.add('tag-appear');
        setTimeout(() => {
          tagElement.classList.remove('tag-appear');
        }, 300);
      }
    });
  }
  
  if (userKeywords && userKeywords.length > 0) {
    userKeywords.forEach(keyword => {
      const tagElement = document.createElement('span');
      tagElement.className = `category-button keyword-button ${activeKeywords.includes(keyword) ? 'active' : ''}`;
      tagElement.textContent = keyword;
      tagElement.dataset.keyword = keyword;
      tagElement.title = "匹配标题和摘要中的关键词";
      
      tagElement.addEventListener('click', () => {
        toggleKeywordFilter(keyword);
      });
      
      filterTagsElement.appendChild(tagElement);
      
      if (!activeKeywords.includes(keyword)) {
        tagElement.classList.add('tag-appear');
        setTimeout(() => {
          tagElement.classList.remove('tag-appear');
        }, 300);
      }
    });
  }
}

// 切换关键词过滤
function toggleKeywordFilter(keyword) {
  const index = activeKeywords.indexOf(keyword);
  
  if (index === -1) {
    activeKeywords.push(keyword);
  } else {
    activeKeywords.splice(index, 1);
  }
  
  const keywordTags = document.querySelectorAll('[data-keyword]');
  keywordTags.forEach(tag => {
    if (tag.dataset.keyword === keyword) {
      tag.classList.remove('tag-highlight');
      tag.classList.toggle('active', activeKeywords.includes(keyword));
      
      setTimeout(() => {
        tag.classList.add('tag-highlight');
      }, 10);
      
      setTimeout(() => {
        tag.classList.remove('tag-highlight');
      }, 1000);
    }
  });
  
  renderPapers();
}

// 切换作者过滤
function toggleAuthorFilter(author) {
  const index = activeAuthors.indexOf(author);
  
  if (index === -1) {
    activeAuthors.push(author);
  } else {
    activeAuthors.splice(index, 1);
  }
  
  const authorTags = document.querySelectorAll('[data-author]');
  authorTags.forEach(tag => {
    if (tag.dataset.author === author) {
      tag.classList.remove('tag-highlight');
      tag.classList.toggle('active', activeAuthors.includes(author));
      
      setTimeout(() => {
        tag.classList.add('tag-highlight');
      }, 10);
      
      setTimeout(() => {
        tag.classList.remove('tag-highlight');
      }, 1000);
    }
  });
  
  renderPapers();
}

document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  fetchGitHubStats();
  loadUserKeywords();
  loadUserAuthors();
  
  fetchAvailableDates().then(() => {
    if (availableDates.length > 0) {
      loadPapersByDate(availableDates[0]);
    }
  });
});

async function fetchGitHubStats() {
  try {
    const response = await fetch('https://api.github.com/repos/dw-dengwei/daily-arXiv-ai-enhanced');
    const data = await response.json();
    const starCount = data.stargazers_count;
    const forkCount = data.forks_count;
    
    document.getElementById('starCount').textContent = starCount;
    document.getElementById('forkCount').textContent = forkCount;
  } catch (error) {
    console.error('获取GitHub统计数据失败:', error);
    document.getElementById('starCount').textContent = '?';
    document.getElementById('forkCount').textContent = '?';
  }
}

function initEventListeners() {
  const calendarButton = document.getElementById('calendarButton');
  calendarButton.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleDatePicker();
  });
  
  const datePickerModal = document.querySelector('.date-picker-modal');
  datePickerModal.addEventListener('click', (event) => {
    if (event.target === datePickerModal) {
      toggleDatePicker();
    }
  });
  
  const datePickerContent = document.querySelector('.date-picker-content');
  datePickerContent.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  document.getElementById('dateRangeMode').addEventListener('change', toggleRangeMode);
  document.getElementById('closeModal').addEventListener('click', closeModal);
  
  document.querySelectorAll('[data-top-list]').forEach(button => {
    button.addEventListener('click', () => loadTopPapers(button.dataset.topList || 'year'));
  });

  const likeButton = document.getElementById('likePaperButton');
  if (likeButton) {
    likeButton.addEventListener('click', toggleCurrentPaperLike);
  }

  const exportLikesButton = document.getElementById('exportLikesButton');
  if (exportLikesButton) {
    exportLikesButton.addEventListener('click', exportLikedPapers);
  }

  const zoteroAddButton = document.getElementById('zoteroAddButton');
  if (zoteroAddButton) {
    zoteroAddButton.addEventListener('click', addCurrentPaperToZotero);
  }
  
  document.querySelector('.paper-modal').addEventListener('click', (event) => {
    const modal = document.querySelector('.paper-modal');
    const pdfContainer = modal.querySelector('.pdf-container');
    
    if (event.target === modal) {
      if (pdfContainer && pdfContainer.classList.contains('expanded')) {
        const expandButton = modal.querySelector('.pdf-expand-btn');
        if (expandButton) {
          togglePdfSize(expandButton);
        }
        event.stopPropagation();
      } else {
        closeModal();
      }
    }
  });
  
  document.addEventListener('keydown', (event) => {
    const activeElement = document.activeElement;
    const isInputFocused = activeElement && (
      activeElement.tagName === 'INPUT' || 
      activeElement.tagName === 'TEXTAREA' || 
      activeElement.isContentEditable
    );
    
    if (event.key === 'Escape') {
      const paperModal = document.getElementById('paperModal');
      const datePickerModal = document.getElementById('datePickerModal');
      
      if (paperModal.classList.contains('active')) {
        closeModal();
      } else if (datePickerModal.classList.contains('active')) {
        toggleDatePicker();
      }
    }
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const paperModal = document.getElementById('paperModal');
      if (paperModal.classList.contains('active')) {
        event.preventDefault();
        
        if (event.key === 'ArrowLeft') {
          navigateToPreviousPaper();
        } else if (event.key === 'ArrowRight') {
          navigateToNextPaper();
        }
      }
    }
    else if (event.key === ' ' || event.key === 'Spacebar') {
      const paperModal = document.getElementById('paperModal');
      const datePickerModal = document.getElementById('datePickerModal');
      
      if (!isInputFocused && !datePickerModal.classList.contains('active')) {
        event.preventDefault();
        event.stopPropagation();
        showRandomPaper();
      }
    }
  });
  
  const categoryScroll = document.querySelector('.category-scroll');
  const keywordScroll = document.querySelector('.keyword-scroll');
  const authorScroll = document.querySelector('.author-scroll');
  
  if (categoryScroll) {
    categoryScroll.addEventListener('wheel', function(e) {
      if (e.deltaY !== 0) {
        e.preventDefault();
        this.scrollLeft += e.deltaY;
      }
    });
  }
  
  if (keywordScroll) {
    keywordScroll.addEventListener('wheel', function(e) {
      if (e.deltaY !== 0) {
        e.preventDefault();
        this.scrollLeft += e.deltaY;
      }
    });
  }
  
  if (authorScroll) {
    authorScroll.addEventListener('wheel', function(e) {
      if (e.deltaY !== 0) {
        e.preventDefault();
        this.scrollLeft += e.deltaY;
      }
    });
  }

  const categoryButtons = document.querySelectorAll('.category-button');
  categoryButtons.forEach(button => {
    button.addEventListener('click', () => {
      const category = button.dataset.category;
      if (category) filterByCategory(category);
    });
  });

  const backToTopButton = document.getElementById('backToTop');
  if (backToTopButton) {
    const updateBackToTopVisibility = () => {
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
      if (scrollTop > 300) {
        backToTopButton.classList.add('visible');
      } else {
        backToTopButton.classList.remove('visible');
      }
    };

    updateBackToTopVisibility();
    window.addEventListener('scroll', updateBackToTopVisibility, { passive: true });

    backToTopButton.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  const searchToggle = document.getElementById('textSearchToggle');
  const searchWrapper = document.querySelector('#textSearchContainer .search-input-wrapper');
  const searchInput = document.getElementById('textSearchInput');
  const searchClear = document.getElementById('textSearchClear');

  if (searchToggle && searchWrapper && searchInput && searchClear) {
    searchToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      searchWrapper.style.display = 'flex';
      searchInput.focus();
    });

    const handleInput = () => {
      const value = searchInput.value.trim();
      textSearchQuery = value;
      if (textSearchQuery.length > 0) {
        if (previousActiveKeywords === null) {
          previousActiveKeywords = [...activeKeywords];
        }
        if (previousActiveAuthors === null) {
          previousActiveAuthors = [...activeAuthors];
        }
        const keywordsToDisable = [...activeKeywords];
        const authorsToDisable = [...activeAuthors];
        keywordsToDisable.forEach(k => toggleKeywordFilter(k));
        authorsToDisable.forEach(a => toggleAuthorFilter(a));
      } else {
        if (previousActiveKeywords && previousActiveKeywords.length > 0) {
          previousActiveKeywords.forEach(k => {
            if (!activeKeywords.includes(k)) toggleKeywordFilter(k);
          });
        }
        if (previousActiveAuthors && previousActiveAuthors.length > 0) {
          previousActiveAuthors.forEach(a => {
            if (!activeAuthors.includes(a)) toggleAuthorFilter(a);
          });
        }
        previousActiveKeywords = null;
        previousActiveAuthors = null;
        searchWrapper.style.display = 'none';
      }

      searchClear.style.display = textSearchQuery.length > 0 ? 'inline-flex' : 'none';
      renderPapers();
    };

    searchInput.addEventListener('input', handleInput);

    searchClear.addEventListener('click', (e) => {
      e.stopPropagation();
      searchInput.value = '';
      textSearchQuery = '';
      searchClear.style.display = 'none';
      if (previousActiveKeywords && previousActiveKeywords.length > 0) {
        previousActiveKeywords.forEach(k => {
          if (!activeKeywords.includes(k)) toggleKeywordFilter(k);
        });
      }
      if (previousActiveAuthors && previousActiveAuthors.length > 0) {
        previousActiveAuthors.forEach(a => {
          if (!activeAuthors.includes(a)) toggleAuthorFilter(a);
        });
      }
      previousActiveKeywords = null;
      previousActiveAuthors = null;
      renderPapers();
      searchWrapper.style.display = 'none';
    });

    searchInput.addEventListener('blur', () => {
      const value = searchInput.value.trim();
      if (value.length === 0) {
        searchWrapper.style.display = 'none';
      }
    });
  }
}

function getPreferredLanguage() {
  const browserLang = navigator.language || navigator.userLanguage;
  if (browserLang.startsWith('zh')) {
    return 'Chinese';
  }
  return 'English';
}

function selectLanguageForDate(date, preferredLanguage = null) {
  const availableLanguages = window.dateLanguageMap?.get(date) || [];
  
  if (availableLanguages.length === 0) {
    return 'English';
  }
  
  const preferred = preferredLanguage || getPreferredLanguage();
  if (availableLanguages.includes(preferred)) {
    return preferred;
  }
  
  return availableLanguages.includes('English') ? 'English' : availableLanguages[0];
}

async function fetchAvailableDates() {
  try {
    const response = await fetch('assets/file-list.txt');
    if (!response.ok) {
      console.error('Error fetching file list:', response.status);
      return [];
    }
    const text = await response.text();
    const files = text.trim().split('\n');

    const dateRegex = /(\d{4}-\d{2}-\d{2})_AI_enhanced_(English|Chinese)\.jsonl/;
    const dateLanguageMap = new Map();
    const dates = [];
    
    files.forEach(file => {
      const match = file.match(dateRegex);
      if (match && match[1] && match[2]) {
        const date = match[1];
        const language = match[2];
        
        if (!dateLanguageMap.has(date)) {
          dateLanguageMap.set(date, []);
          dates.push(date);
        }
        dateLanguageMap.get(date).push(language);
      }
    });
    
    window.dateLanguageMap = dateLanguageMap;
    availableDates = [...new Set(dates)];
    availableDates.sort((a, b) => new Date(b) - new Date(a));

    initDatePicker();

    return availableDates;
  } catch (error) {
    console.error('获取可用日期失败:', error);
  }
}

function initDatePicker() {
  const datepickerInput = document.getElementById('datepicker');
  
  if (flatpickrInstance) {
    flatpickrInstance.destroy();
  }
  
  const enabledDatesMap = {};
  availableDates.forEach(date => {
    enabledDatesMap[date] = true;
  });
  
  flatpickrInstance = flatpickr(datepickerInput, {
    inline: true,
    dateFormat: "Y-m-d",
    defaultDate: availableDates[0],
    enable: [
      function(date) {
        const dateStr = date.getFullYear() + "-" +
                        String(date.getMonth() + 1).padStart(2, '0') + "-" +
                        String(date.getDate()).padStart(2, '0');
        return dateStr <= availableDates[0];
      }
    ],
    onChange: function(selectedDates, dateStr) {
      if (isRangeMode && selectedDates.length === 2) {
        const startDate = formatDateForAPI(selectedDates[0]);
        const endDate = formatDateForAPI(selectedDates[1]);
        loadPapersByDateRange(startDate, endDate);
        toggleDatePicker();
      } else if (!isRangeMode && selectedDates.length === 1) {
        const selectedDate = formatDateForAPI(selectedDates[0]);
        loadPapersByDate(selectedDate);
        toggleDatePicker();
      }
    }
  });
  
  const inputElement = document.querySelector('.flatpickr-input');
  if (inputElement) {
    inputElement.style.display = 'none';
  }
}

function formatDateForAPI(date) {
  return date.getFullYear() + "-" + 
         String(date.getMonth() + 1).padStart(2, '0') + "-" + 
         String(date.getDate()).padStart(2, '0');
}

function toggleRangeMode() {
  isRangeMode = document.getElementById('dateRangeMode').checked;
  
  if (flatpickrInstance) {
    flatpickrInstance.set('mode', isRangeMode ? 'range' : 'single');
  }
}

async function loadPapersByDate(date) {
  isTop100Mode = false; // 💡 切换回普通日期查看，关闭高分推荐模式
  currentTopListMode = null;
  currentDate = date;
  document.getElementById('currentDate').textContent = formatDate(date);
  
  if (flatpickrInstance) {
    flatpickrInstance.setDate(date, false);
  }
  
  const container = document.getElementById('paperContainer');
  container.innerHTML = `
    <div class="loading-container">
      <div class="loading-spinner"></div>
      <p>Loading paper...</p>
    </div>
  `;
  
  try {
    const selectedLanguage = selectLanguageForDate(date);
    const response = await fetch(`data/${date}_AI_enhanced_${selectedLanguage}.jsonl`);
    if (!response.ok) {
      if (response.status === 404) {
        container.innerHTML = `
          <div class="loading-container">
            <p>No papers found for this date.</p>
          </div>
        `;
        paperData = {};
        renderCategoryFilter({ sortedCategories: [], categoryCounts: {} });
        return;
      }
      throw new Error(`HTTP ${response.status}`);
    }
    const text = await response.text();
    if (!text || text.trim() === '') {
      container.innerHTML = `
        <div class="loading-container">
          <p>No papers found for this date.</p>
        </div>
      `;
      paperData = {};
      renderCategoryFilter({ sortedCategories: [], categoryCounts: {} });
      return;
    }
    
    paperData = parseJsonlData(text, date);
    const categories = getAllCategories(paperData);
    renderCategoryFilter(categories);
    renderPapers();
  } catch (error) {
    console.error('加载论文数据失败:', error);
    container.innerHTML = `
      <div class="loading-container">
        <p>Loading data fails. Please retry.</p>
        <p>Error messages: ${error.message}</p>
      </div>
    `;
  }
}

async function loadTopPapers(mode = 'year') {
  const config = TOP_LISTS[mode] || TOP_LISTS.year;
  isTop100Mode = true;
  currentTopListMode = mode;
  currentCategory = 'all';
  document.getElementById('currentDate').textContent = config.label;
  
  const container = document.getElementById('paperContainer');
  container.innerHTML = `
    <div class="loading-container">
      <div class="loading-spinner"></div>
      <p>Loading ${config.label} papers...</p>
    </div>
  `;
  
  try {
    const response = await fetch(`data/${config.file}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const text = await response.text();
    if (!text || text.trim() === '') {
      container.innerHTML = `
        <div class="loading-container">
          <p>No ${config.label} papers found.</p>
        </div>
      `;
      paperData = {};
      renderCategoryFilter({ sortedCategories: [], categoryCounts: {} });
      return;
    }
    
    paperData = parseJsonlData(text, config.label);
    const categories = getAllCategories(paperData);
    renderCategoryFilter(categories);
    renderPapers();
  } catch (error) {
    console.error('加载历史榜单数据失败:', error);
    container.innerHTML = `
      <div class="loading-container">
        <p>Loading ${config.label} data fails. Please retry.</p>
        <p>Error messages: ${error.message}</p>
      </div>
    `;
  }
}

function loadTop100Papers() {
  return loadTopPapers('year');
}

function parseJsonlData(jsonlText, date) {
  const result = {};
  const lines = jsonlText.trim().split('\n');
  
  lines.forEach(line => {
    try {
      const paper = JSON.parse(line);
      
      if (!paper.categories) {
        return;
      }
      
      let allCategories = Array.isArray(paper.categories) ? paper.categories : [paper.categories];
      const primaryCategory = allCategories[0];
      
      if (!result[primaryCategory]) {
        result[primaryCategory] = [];
      }
      
      const summary = paper.AI && paper.AI.tldr ? paper.AI.tldr : paper.summary;
      
      result[primaryCategory].push({
        title: paper.title,
        url: paper.abs || paper.pdf || `https://arxiv.org/abs/${paper.id}`,
        authors: Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors,
        category: allCategories,
        summary: summary,
        details: paper.summary || '',
        date: paper.date || date, // 💡 优化：优先使用每篇论文自带的历史日期，防止全部显示为 "Top 100"
        id: paper.id,
        motivation: paper.AI && paper.AI.motivation ? paper.AI.motivation : '',
        method: paper.AI && paper.AI.method ? paper.AI.method : '',
        result: paper.AI && paper.AI.result ? paper.AI.result : '',
        conclusion: paper.AI && paper.AI.conclusion ? paper.AI.conclusion : '',
        abstractZh: paper.artifacts && paper.artifacts.abstract_zh ? paper.artifacts.abstract_zh : '',
        conclusionZh: paper.artifacts && paper.artifacts.conclusion_zh ? paper.artifacts.conclusion_zh : '',
        figures: paper.artifacts && Array.isArray(paper.artifacts.figures) ? paper.artifacts.figures : [],
        recommendation: paper.recommendation || null
      });
    } catch (error) {
      console.error('解析JSON行失败:', error, line);
    }
  });
  
  return result;
}

// 获取所有类别并按偏好排序
function getAllCategories(data) {
  const categories = Object.keys(data);
  const catePaperCount = {};
  
  categories.forEach(category => {
    catePaperCount[category] = data[category] ? data[category].length : 0;
  });
  
  return {
    sortedCategories: categories.sort((a, b) => {
      return a.localeCompare(b);
    }),
    categoryCounts: catePaperCount
  };
}

function renderCategoryFilter(categories) {
  const container = document.querySelector('.category-scroll');
  const { sortedCategories, categoryCounts } = categories;
  
  let totalPapers = 0;
  Object.values(categoryCounts).forEach(count => {
    totalPapers += count;
  });
  
  const topButtons = Object.entries(TOP_LISTS).map(([mode, config]) => {
    const active = isTop100Mode && currentTopListMode === mode ? 'active' : '';
    return `<button class="category-button top-list-button ${active}" data-top-list="${mode}">🔥 ${config.shortLabel}</button>`;
  }).join('');

  container.innerHTML = `
    <button class="category-button ${(!isTop100Mode && currentCategory === 'all') ? 'active' : ''}" data-category="all">All<span class="category-count">${totalPapers}</span></button>
    ${topButtons}
  `;
  
  container.querySelectorAll('[data-top-list]').forEach(button => {
    button.addEventListener('click', () => loadTopPapers(button.dataset.topList || 'year'));
  });
  
  sortedCategories.forEach(category => {
    const count = categoryCounts[category];
    const button = document.createElement('button');
    button.className = `category-button ${(!isTop100Mode && category === currentCategory) ? 'active' : ''}`;
    button.innerHTML = `${category}<span class="category-count">${count}</span>`;
    button.dataset.category = category;
    button.addEventListener('click', () => {
      filterByCategory(category);
    });
    
    container.appendChild(button);
  });
  
  document.querySelector('.category-button[data-category="all"]').addEventListener('click', () => {
    isTop100Mode = false; // 点击 All 恢复常规，交由 filterByCategory 处理
    currentTopListMode = null;
    filterByCategory('all');
  });
}

function filterByCategory(category) {
  currentCategory = category;
  
  document.querySelectorAll('.category-button').forEach(button => {
    if (button.dataset.topList) {
      button.classList.toggle('active', isTop100Mode && button.dataset.topList === currentTopListMode);
    } else {
      // 如果是在高分模式下进行二级子分类检索，不取消高分按钮高亮
      button.classList.toggle('active', !isTop100Mode && button.dataset.category === category);
    }
  });
  
  renderFilterTags();
  
  window.scrollTo({
    top: 0,
    behavior: 'smooth'
  });
  
  renderPapers();
}

// 帮助函数：高亮文本中的匹配内容
function highlightMatches(text, terms, className = 'highlight-match') {
  if (!terms || terms.length === 0 || !text) {
    return text;
  }
  
  let result = text;
  const sortedTerms = [...terms].sort((a, b) => b.length - a.length);
  
  sortedTerms.forEach(term => {
    const regex = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    result = result.replace(regex, `<span class="${className}">$1</span>`);
  });
  
  return result;
}

function renderPapers() {
  const container = document.getElementById('paperContainer');
  container.innerHTML = '';
  container.className = `paper-container ${currentView === 'list' ? 'list-view' : ''}`;
  
  let papers = [];
  if (currentCategory === 'all') {
    const { sortedCategories } = getAllCategories(paperData);
    sortedCategories.forEach(category => {
      if (paperData[category]) {
        papers = papers.concat(paperData[category]);
      }
    });
  } else if (paperData[currentCategory]) {
    papers = paperData[currentCategory];
  }
  
  let filteredPapers = [...papers];
  filteredPapers.sort(compareByRecommendation);

  filteredPapers.forEach(p => {
    p.isMatched = false;
    p.matchReason = undefined;
  });

  if (textSearchQuery && textSearchQuery.trim().length > 0) {
    const q = textSearchQuery.toLowerCase();

    filteredPapers.sort((a, b) => {
      const hayA = [
        a.title,
        a.authors,
        Array.isArray(a.category) ? a.category.join(', ') : a.category,
        a.summary,
        a.details || '',
        a.motivation || '',
        a.method || '',
        a.result || '',
        a.conclusion || '',
        a.abstractZh || '',
        a.conclusionZh || '',
        ...(a.figures || []).map(fig => `${fig.figure_label || ''} ${fig.caption_en || ''} ${fig.caption_zh || ''}`)
      ].join(' ').toLowerCase();
      const hayB = [
        b.title,
        b.authors,
        Array.isArray(b.category) ? b.category.join(', ') : b.category,
        b.summary,
        b.details || '',
        b.motivation || '',
        b.method || '',
        b.result || '',
        b.conclusion || '',
        b.abstractZh || '',
        b.conclusionZh || '',
        ...(b.figures || []).map(fig => `${fig.figure_label || ''} ${fig.caption_en || ''} ${fig.caption_zh || ''}`)
      ].join(' ').toLowerCase();
      const am = hayA.includes(q);
      const bm = hayB.includes(q);
      if (am && !bm) return -1;
      if (!am && bm) return 1;
      return 0;
    });

    filteredPapers.forEach(p => {
      const hay = [
        p.title,
        p.authors,
        Array.isArray(p.category) ? p.category.join(', ') : p.category,
        p.summary,
        p.details || '',
        p.motivation || '',
        p.method || '',
        p.result || '',
        p.conclusion || '',
        p.abstractZh || '',
        p.conclusionZh || '',
        ...(p.figures || []).map(fig => `${fig.figure_label || ''} ${fig.caption_en || ''} ${fig.caption_zh || ''}`)
      ].join(' ').toLowerCase();
      const matched = hay.includes(q);
      p.isMatched = matched;
      p.matchReason = matched ? [`文本: ${textSearchQuery}`] : undefined;
    });
  } else {
    if (activeKeywords.length > 0 || activeAuthors.length > 0) {
      filteredPapers.sort((a, b) => {
        const aMatchesKeyword = activeKeywords.length > 0 ? 
          activeKeywords.some(keyword => {
            const searchText = `${a.title} ${a.summary}`.toLowerCase();
            return searchText.includes(keyword.toLowerCase());
          }) : false;
          
        const aMatchesAuthor = activeAuthors.length > 0 ?
          activeAuthors.some(author => {
            return a.authors.toLowerCase().includes(author.toLowerCase());
          }) : false;
          
        const bMatchesKeyword = activeKeywords.length > 0 ?
          activeKeywords.some(keyword => {
            const searchText = `${b.title} ${b.summary}`.toLowerCase();
            return searchText.includes(keyword.toLowerCase());
          }) : false;
          
        const bMatchesAuthor = activeAuthors.length > 0 ?
          activeAuthors.some(author => {
            return b.authors.toLowerCase().includes(author.toLowerCase());
          }) : false;
      
        const aMatches = aMatchesKeyword || aMatchesAuthor;
        const bMatches = bMatchesKeyword || bMatchesAuthor;
        
        if (aMatches && !bMatches) return -1;
        if (!aMatches && bMatches) return 1;
        return 0;
      });
      
      filteredPapers.forEach(paper => {
        const matchesKeyword = activeKeywords.length > 0 ?
          activeKeywords.some(keyword => {
            const searchText = `${paper.title} ${paper.summary}`.toLowerCase();
            return searchText.includes(keyword.toLowerCase());
          }) : false;
          
        const matchesAuthor = activeAuthors.length > 0 ?
          activeAuthors.some(author => {
            return paper.authors.toLowerCase().includes(author.toLowerCase());
          }) : false;
          
        paper.isMatched = matchesKeyword || matchesAuthor;
        
        if (paper.isMatched) {
          paper.matchReason = [];
          if (matchesKeyword) {
            const matchedKeywords = activeKeywords.filter(keyword => 
              `${paper.title} ${paper.summary}`.toLowerCase().includes(keyword.toLowerCase())
            );
            if (matchedKeywords.length > 0) {
              paper.matchReason.push(`关键词: ${matchedKeywords.join(', ')}`);
            }
          }
          if (matchesAuthor) {
            const matchedAuthors = activeAuthors.filter(author => 
              paper.authors.toLowerCase().includes(author.toLowerCase())
            );
            if (matchedAuthors.length > 0) {
              paper.matchReason.push(`作者: ${matchedAuthors.join(', ')}`);
            }
          }
        }
      });
    }
  }
  
  currentFilteredPapers = [...filteredPapers];
  
  if (filteredPapers.length === 0) {
    container.innerHTML = `
      <div class="loading-container">
        <p>No paper found.</p>
      </div>
    `;
    return;
  }
  
  filteredPapers.forEach((paper, index) => {
    const paperCard = document.createElement('div');
    paperCard.className = `paper-card ${paper.isMatched ? 'matched-paper' : ''}`;
    paperCard.dataset.id = paper.id || paper.url;
    
    if (paper.isMatched) {
      paperCard.title = `匹配: ${paper.matchReason.join(' | ')}`;
    }
    
    const categoryTags = paper.allCategories ? 
      paper.allCategories.map(cat => `<span class="category-tag">${cat}</span>`).join('') : 
      `<span class="category-tag">${paper.category}</span>`;
    const recommendation = paper.recommendation || {};
    const recommendationScore = Number(recommendation.score || 0);
    const recommendationStars = renderStars(recommendation.stars || 1);
    const recommendationReason = recommendation.reason || '暂无个性化推荐说明。';
    const recommendationClass = recommendationScore >= 80 ? 'high' : recommendationScore >= 50 ? 'medium' : 'low';
    
    const titleSummaryTerms = [];
    if (activeKeywords.length > 0) {
      titleSummaryTerms.push(...activeKeywords);
    }
    if (textSearchQuery && textSearchQuery.trim().length > 0) {
      titleSummaryTerms.push(textSearchQuery.trim());
    }

    const highlightedTitle = titleSummaryTerms.length > 0 
      ? highlightMatches(paper.title, titleSummaryTerms, 'keyword-highlight') 
      : paper.title;
    const highlightedSummary = titleSummaryTerms.length > 0 
      ? highlightMatches(paper.summary, titleSummaryTerms, 'keyword-highlight') 
      : paper.summary;

    const authorTerms = [];
    if (activeAuthors.length > 0) authorTerms.push(...activeAuthors);
    if (textSearchQuery && textSearchQuery.trim().length > 0) authorTerms.push(textSearchQuery.trim());
    const highlightedAuthors = authorTerms.length > 0 
      ? highlightMatches(paper.authors, authorTerms, 'author-highlight') 
      : paper.authors;
    
    paperCard.innerHTML = `
      <div class="paper-card-index">${index + 1}</div>
      ${paper.isMatched ? '<div class="match-badge" title="匹配您的搜索条件"></div>' : ''}
      <div class="paper-card-header">
        <div class="recommendation-strip ${recommendationClass}" title="${recommendationReason}">
          <span class="recommendation-stars">${recommendationStars}</span>
          <span class="recommendation-score">${recommendationScore}/100</span>
        </div>
        <h3 class="paper-card-title">${highlightedTitle}</h3>
        <p class="paper-card-authors">${highlightedAuthors}</p>
        <div class="paper-card-categories">
          ${categoryTags}
        </div>
      </div>
      <div class="paper-card-body">
        <p class="paper-card-summary">${highlightedSummary}</p>
        <p class="recommendation-reason">${recommendationReason}</p>
        <div class="paper-card-footer">
          <span class="paper-card-date">${formatDate(paper.date)}</span>
          <span class="paper-card-link">Details</span>
        </div>
      </div>
    `;
    
    paperCard.addEventListener('click', () => {
      currentPaperIndex = index;
      showPaperDetails(paper, index + 1);
    });
    
    container.appendChild(paperCard);
  });
}

function showPaperDetails(paper, paperIndex) {
  const modal = document.getElementById('paperModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const paperLink = document.getElementById('paperLink');
  const pdfLink = document.getElementById('pdfLink');
  const htmlLink = document.getElementById('htmlLink');
  
  modalBody.scrollTop = 0;
  
  const modalTitleTerms = [];
  if (activeKeywords.length > 0) modalTitleTerms.push(...activeKeywords);
  if (textSearchQuery && textSearchQuery.trim().length > 0) modalTitleTerms.push(textSearchQuery.trim());
  const highlightedTitle = modalTitleTerms.length > 0 
    ? highlightMatches(paper.title, modalTitleTerms, 'keyword-highlight') 
    : paper.title;
  
  modalTitle.innerHTML = paperIndex ? `<span class="paper-index-badge">${paperIndex}</span> ${highlightedTitle}` : highlightedTitle;
  
  const abstractText = paper.details || '';
  const categoryDisplay = paper.allCategories ? paper.allCategories.join(', ') : paper.category;
  
  const modalAuthorTerms = [];
  if (activeAuthors.length > 0) modalAuthorTerms.push(...activeAuthors);
  if (textSearchQuery && textSearchQuery.trim().length > 0) modalAuthorTerms.push(textSearchQuery.trim());
  const highlightedAuthors = modalAuthorTerms.length > 0 
    ? highlightMatches(paper.authors, modalAuthorTerms, 'author-highlight') 
    : paper.authors;
  
  const highlightedSummary = modalTitleTerms.length > 0 
    ? highlightMatches(paper.summary, modalTitleTerms, 'keyword-highlight') 
    : paper.summary;
  
  const highlightedAbstract = modalTitleTerms.length > 0 
    ? highlightMatches(abstractText, modalTitleTerms, 'keyword-highlight') 
    : abstractText;
  
  const highlightedMotivation = paper.motivation && modalTitleTerms.length > 0 
    ? highlightMatches(paper.motivation, modalTitleTerms, 'keyword-highlight') 
    : paper.motivation;
  
  const highlightedMethod = paper.method && modalTitleTerms.length > 0 
    ? highlightMatches(paper.method, modalTitleTerms, 'keyword-highlight') 
    : paper.method;
  
  const highlightedResult = paper.result && modalTitleTerms.length > 0 
    ? highlightMatches(paper.result, modalTitleTerms, 'keyword-highlight') 
    : paper.result;
  
  const highlightedConclusion = paper.conclusion && modalTitleTerms.length > 0 
    ? highlightMatches(paper.conclusion, modalTitleTerms, 'keyword-highlight') 
    : paper.conclusion;

  const highlightedAbstractZh = paper.abstractZh && modalTitleTerms.length > 0
    ? highlightMatches(paper.abstractZh, modalTitleTerms, 'keyword-highlight')
    : paper.abstractZh;

  const highlightedConclusionZh = paper.conclusionZh && modalTitleTerms.length > 0
    ? highlightMatches(paper.conclusionZh, modalTitleTerms, 'keyword-highlight')
    : paper.conclusionZh;

  const figuresHtml = paper.figures && paper.figures.length > 0
    ? paper.figures.map((figure, idx) => {
        const label = figure.figure_label || `Figure ${idx + 1}`;
        const captionZh = figure.caption_zh || '';
        const captionEn = figure.caption_en || '';
        const imageUrl = normalizeFigureImageUrl(figure.image_url);
        const image = imageUrl
          ? `<img src="${imageUrl}" alt="${label}" loading="lazy" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';"><a class="figure-source-link" href="${imageUrl}" target="_blank" style="display:none;">打开图片源</a>`
          : '';
        return `
          <div class="figure-item">
            <h4>${label}</h4>
            ${image}
            ${captionZh ? `<p class="figure-caption-zh">${captionZh}</p>` : ''}
            ${captionEn ? `<p class="figure-caption-en">${captionEn}</p>` : ''}
          </div>
        `;
      }).join('')
    : '';
  
  const matchedPaperClass = paper.isMatched ? 'matched-paper-details' : '';
  const recommendation = paper.recommendation || {};
  const recommendationScore = Number(recommendation.score || 0);
  const recommendationStars = renderStars(recommendation.stars || 1);
  const recommendationReason = recommendation.reason || '暂无个性化推荐说明。';
  const matchedTopics = [
    ...(recommendation.matched_topics || []),
    ...(recommendation.matched_authors || [])
  ];
  const matchedTopicsHtml = matchedTopics.length > 0
    ? `<p><strong>Matched profile: </strong>${matchedTopics.join(', ')}</p>`
    : '';
  
  const modalContent = `
    <div class="paper-details ${matchedPaperClass}">
      <div class="recommendation-panel">
        <div class="recommendation-panel-score">
          <span class="recommendation-stars">${recommendationStars}</span>
          <span>${recommendationScore}/100</span>
        </div>
        <p>${recommendationReason}</p>
        ${matchedTopicsHtml}
      </div>
      <p><strong>Authors: </strong>${highlightedAuthors}</p>
      <p><strong>Categories: </strong>${categoryDisplay}</p>
      <p><strong>Date: </strong>${formatDate(paper.date)}</p>
      
      <h3>TL;DR</h3>
      <p>${highlightedSummary}</p>
      
      <div class="paper-sections">
        ${paper.motivation ? `<div class="paper-section"><h4>Motivation</h4><p>${highlightedMotivation}</p></div>` : ''}
        ${paper.method ? `<div class="paper-section"><h4>Method</h4><p>${highlightedMethod}</p></div>` : ''}
        ${paper.result ? `<div class="paper-section"><h4>Result</h4><p>${highlightedResult}</p></div>` : ''}
        ${paper.conclusion ? `<div class="paper-section"><h4>Conclusion</h4><p>${highlightedConclusion}</p></div>` : ''}
      </div>
      
      ${highlightedAbstract ? `<h3>Abstract</h3><p class="original-abstract">${highlightedAbstract}</p>` : ''}

      <div class="paper-extra-sections">
        ${highlightedAbstractZh ? `
          <details class="paper-extra" open>
            <summary>摘要翻译</summary>
            <p>${highlightedAbstractZh}</p>
          </details>
        ` : ''}
        ${highlightedConclusionZh ? `
          <details class="paper-extra">
            <summary>结论翻译</summary>
            <p>${highlightedConclusionZh}</p>
          </details>
        ` : ''}
        ${figuresHtml ? `
          <details class="paper-extra">
            <summary>重点图片</summary>
            <div class="figure-list">${figuresHtml}</div>
          </details>
        ` : ''}
      </div>
      
      <div class="pdf-preview-section">
        <div class="pdf-header">
          <h3>PDF Preview</h3>
          <button class="pdf-expand-btn" onclick="togglePdfSize(this)">
            <svg class="expand-icon" viewBox="0 0 24 24" width="24" height="24">
              <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>
            </svg>
            <svg class="collapse-icon" viewBox="0 0 24 24" width="24" height="24" style="display: none;">
              <path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>
            </svg>
          </button>
        </div>
        <div class="pdf-container">
          <iframe src="${paper.url.replace('abs', 'pdf')}" width="100%" height="800px" frameborder="0"></iframe>
        </div>
      </div>
    </div>
  `;
  
  document.getElementById('modalBody').innerHTML = modalContent;
  document.getElementById('paperLink').href = paper.url;
  document.getElementById('pdfLink').href = paper.url.replace('abs', 'pdf');
  document.getElementById('htmlLink').href = paper.url.replace('abs', 'html');
  
  const prompt = `请你阅读这篇文章${paper.url.replace('abs', 'pdf')},总结一下这篇文章解决的问题、相关工作、研究方法、做了什么实验及其结果、结论，最后整体总结一下这篇文章的内容`;
  document.getElementById('kimiChatLink').href = `https://www.kimi.com/_prefill_chat?prefill_prompt=${prompt}&system_prompt=你是一个学术助手，后面的对话将围绕着以下论文内容进行，已经通过链接给出了论文的PDF和论文已有的FAQ。用户将继续向你咨询论文的相关问题，请你作出专业的回答，不要出现第一人称，当涉及到分点回答时，鼓励你以markdown格式输出。&send_immediately=true&force_search=true`;
  
  const paperPosition = document.getElementById('paperPosition');
  if (paperPosition && currentFilteredPapers.length > 0) {
    paperPosition.textContent = `${currentPaperIndex + 1} / ${currentFilteredPapers.length}`;
  }

  updateLikeButton(paper);
  
  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  const modal = document.getElementById('paperModal');
  const modalBody = document.getElementById('modalBody');
  
  modalBody.scrollTop = 0;
  modal.classList.remove('active');
  document.body.style.overflow = '';
}

function navigateToPreviousPaper() {
  if (currentFilteredPapers.length === 0) return;
  
  currentPaperIndex = currentPaperIndex > 0 ? currentPaperIndex - 1 : currentFilteredPapers.length - 1;
  const paper = currentFilteredPapers[currentPaperIndex];
  showPaperDetails(paper, currentPaperIndex + 1);
}

function navigateToNextPaper() {
  if (currentFilteredPapers.length === 0) return;
  
  currentPaperIndex = currentPaperIndex < currentFilteredPapers.length - 1 ? currentPaperIndex + 1 : 0;
  const paper = currentFilteredPapers[currentPaperIndex];
  showPaperDetails(paper, currentPaperIndex + 1);
}

function showRandomPaper() {
  if (currentFilteredPapers.length === 0) {
    console.log('No papers available to show random paper');
    return;
  }
  
  const randomIndex = Math.floor(Math.random() * currentFilteredPapers.length);
  const randomPaper = currentFilteredPapers[randomIndex];
  
  currentPaperIndex = randomIndex;
  showPaperDetails(randomPaper, currentPaperIndex + 1);
  showRandomPaperIndicator();
  
  console.log(`Showing random paper: ${randomIndex + 1}/${currentFilteredPapers.length}`);
}

function showRandomPaperIndicator() {
  const existingIndicator = document.querySelector('.random-paper-indicator');
  if (existingIndicator) {
    existingIndicator.remove();
  }
  
  const indicator = document.createElement('div');
  indicator.className = 'random-paper-indicator';
  indicator.textContent = 'Random Paper';
  
  document.body.appendChild(indicator);
  
  setTimeout(() => {
    if (indicator && indicator.parentNode) {
      indicator.remove();
    }
  }, 3000);
}

function toggleDatePicker() {
  const datePicker = document.getElementById('datePickerModal');
  datePicker.classList.toggle('active');
  
  if (datePicker.classList.contains('active')) {
    document.body.style.overflow = 'hidden';
    
    if (flatpickrInstance && !isTop100Mode) {
      flatpickrInstance.setDate(currentDate, false);
    }
  } else {
    document.body.style.overflow = '';
  }
}

function toggleView() {
  currentView = currentView === 'grid' ? 'list' : 'grid';
  document.getElementById('paperContainer').classList.toggle('list-view', currentView === 'list');
}

function formatDate(dateString) {
  // 兼容 Top 100 静态标记或未定义字段
  if (!dateString || dateString === 'Top 100') return 'Top 榜单';
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return dateString;
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric'
  });
}

async function loadPapersByDateRange(startDate, endDate) {
  isTop100Mode = false; // 切换回普通时间跨度检索，关闭高分模式
  currentTopListMode = null;
  const validDatesInRange = availableDates.filter(date => {
    return date >= startDate && date <= endDate;
  });
  
  if (validDatesInRange.length === 0) {
    alert('No available papers in the selected date range.');
    return;
  }
  
  currentDate = `${startDate} to ${endDate}`;
  document.getElementById('currentDate').textContent = `${formatDate(startDate)} - ${formatDate(endDate)}`;
  
  const container = document.getElementById('paperContainer');
  container.innerHTML = `
    <div class="loading-container">
      <div class="loading-spinner"></div>
      <p>Loading papers from ${formatDate(startDate)} to ${formatDate(endDate)}...</p>
    </div>
  `;
  
  try {
    const allPaperData = {};
    
    for (const date of validDatesInRange) {
      const selectedLanguage = selectLanguageForDate(date);
      const response = await fetch(`data/${date}_AI_enhanced_${selectedLanguage}.jsonl`);
      const text = await response.text();
      const dataPapers = parseJsonlData(text, date);
      
      Object.keys(dataPapers).forEach(category => {
        if (!allPaperData[category]) {
          allPaperData[category] = [];
        }
        allPaperData[category] = allPaperData[category].concat(dataPapers[category]);
      });
    }
    
    paperData = allPaperData;
    const categories = getAllCategories(paperData);
    renderCategoryFilter(categories);
    renderPapers();
  } catch (error) {
    console.error('加载论文数据失败:', error);
    container.innerHTML = `
      <div class="loading-container">
        <p>Loading data fails. Please retry.</p>
        <p>Error messages: ${error.message}</p>
      </div>
    `;
  }
}

function clearAllKeywords() {
  activeKeywords = [];
  renderPapers();
}

function clearAllAuthors() {
  activeAuthors = [];
  renderFilterTags();
  renderPapers();
}

function togglePdfSize(button) {
  const pdfContainer = button.closest('.pdf-preview-section').querySelector('.pdf-container');
  const iframe = pdfContainer.querySelector('iframe');
  const expandIcon = button.querySelector('.expand-icon');
  const collapseIcon = button.querySelector('.collapse-icon');
  
  if (pdfContainer.classList.contains('expanded')) {
    pdfContainer.classList.remove('expanded');
    iframe.style.height = '800px';
    expandIcon.style.display = 'block';
    collapseIcon.style.display = 'none';
    
    const overlay = document.querySelector('.pdf-overlay');
    if (overlay) {
      overlay.remove();
    }
  } else {
    pdfContainer.classList.add('expanded');
    iframe.style.height = '90vh';
    expandIcon.style.display = 'none';
    collapseIcon.style.display = 'block';
    
    const overlay = document.createElement('div');
    overlay.className = 'pdf-overlay';
    document.body.appendChild(overlay);
    
    overlay.addEventListener('click', () => {
      togglePdfSize(button);
    });
  }
}
