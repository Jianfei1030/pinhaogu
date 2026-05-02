// news_v2.js - 新闻加载与管理（统一入口）
// 职责：
// 1. 监控 Tab 侧边栏新闻：最多 20 条，增量更新
// 2. 新闻 Tab 全屏新闻：全量加载（500+ 条）
// 3. 盘前分析/复盘展示
// Updated: 2026-04-08 - 重构为单一清晰路径

console.log('[news_v2.js] Loading...');

// ==================== 状态管理 ====================

// 全局持久化日期 Key（供 analysis.js / review.js 共用）
const STOCK_UI_DATE_KEY = 'stock-ui-selected-date';

var NewsState = {
  lastNewsTime: '',              // 增量游标
  sidebarInitialized: false,     // 侧边栏是否已初始化
  newsTabInitialized: false,     // 新闻 Tab 是否已渲染
  currentDate: '',               // 当前选择的日期
  refreshInterval: 60000         // 刷新间隔（毫秒）
};

// ==================== 工具函数 ====================

function getSelectedNewsDate() {
  const input = document.getElementById('newsDateInput');
  return input ? input.value : new Date().toISOString().slice(0, 10);
}

function formatPct(pct) {
  if (pct === undefined || pct === null) return '-';
  const sign = pct > 0 ? '+' : '';
  return sign + Number(pct).toFixed(2) + '%';
}

function colorPct(pct) {
  if (pct > 0) return '#22c55e';
  if (pct < 0) return '#ef4444';
  return 'var(--muted,#9aa5ce)';
}

function createNewsItemHTML(item) {
  const hasSummary = item.summary && item.summary.trim().length > 0;
  return `
    <div class="news-item-fullscreen">
      <div class="news-item-header">
        <span class="news-item-time">${item.time}</span>
        <span class="news-item-source">${item.source || ''}</span>
      </div>
      <div class="news-item-title">${item.title}</div>
      ${hasSummary ? `<div class="news-item-summary">${item.summary}</div>` : ''}
    </div>
  `;
}

function createSidebarNewsItem(item) {
  const div = document.createElement('div');
  div.className = 'sidebar-news-item';
  const hasSummary = item.summary && item.summary.trim().length > 0;
  div.innerHTML = `
    <div class="sidebar-news-header">
      <span class="sidebar-news-time">${item.time}</span>
      <span class="sidebar-news-source">${item.source || ''}</span>
    </div>
    <div class="sidebar-news-title">${item.title}</div>
    ${hasSummary ? `<div class="sidebar-news-summary">${item.summary}</div>` : ''}
  `;
  return div;
}

// ==================== 核心新闻加载函数 ====================

/**
 * 加载新闻数据
 * @param {boolean} isFullDay - 是否加载全量（新闻 Tab 用）
 * @param {boolean} isSidebar - 是否更新侧边栏
 * @returns {Promise<Array>} 新闻数组
 */
async function fetchNewsData(isFullDay = false) {
  const limit = isFullDay ? 5000 : 20;
  const afterParam = !isFullDay && NewsState.lastNewsTime ? `&after=${encodeURIComponent(NewsState.lastNewsTime)}` : '';
  const url = `/api/news/recent?date=today&limit=${limit}${afterParam}`;
  
  try {
    const res = await fetch(url);
    const data = await res.json();
    
    if (!data.news || data.news.length === 0) {
      return [];
    }
    
    // 更新游标
    if (data.last_time) {
      NewsState.lastNewsTime = data.last_time;
    }
    
    return data.news;
  } catch(e) {
    console.warn('[news_v2] fetch failed:', e);
    return [];
  }
}

/**
 * 渲染新闻到侧边栏（监控 Tab）
 * @param {Array} newsItems - 新闻数组
 * @param {boolean} clearFirst - 是否先清空
 */
function renderSidebarNews(newsItems, clearFirst = false) {
  const sidebarList = document.getElementById('monitorNewsList');
  if (!sidebarList) {
    console.warn('[news_v2] monitorNewsList not found');
    return;
  }
  
  if (clearFirst) {
    sidebarList.innerHTML = '';
  }
  
  // 只保留最新 20 条
  const itemsToShow = newsItems.slice(0, 20);
  
  // 如果是首次加载且没有数据，显示空状态
  if (itemsToShow.length === 0 && sidebarList.children.length === 0) {
    sidebarList.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--muted); font-size: 12px;">
        暂无新闻
      </div>
    `;
    return;
  }
  
  // 清空空状态
  if (itemsToShow.length > 0 && sidebarList.querySelector('[style*="暂无新闻"]')) {
    sidebarList.innerHTML = '';
  }
  
  itemsToShow.forEach(item => {
    const div = createSidebarNewsItem(item);
    sidebarList.insertBefore(div, sidebarList.firstChild);
  });
  
  // 保持最多 20 条
  while (sidebarList.children.length > 20) {
    sidebarList.removeChild(sidebarList.lastChild);
  }
}

/**
 * 渲染新闻到新闻 Tab（全屏）
 * @param {Array} newsItems - 新闻数组
 */
function renderNewsTab(newsItems) {
  const newsTabList = document.getElementById('newsTabList');
  if (!newsTabList) {
    console.warn('[news_v2] newsTabList not found');
    return;
  }
  
  // 显示加载状态
  if (newsItems.length === 0) {
    newsTabList.innerHTML = `
      <div class="news-empty-state">
        <div class="news-empty-icon">📰</div>
        <div class="news-empty-title">暂无新闻</div>
        <div class="news-empty-desc">该日期暂无财经新闻，请尝试选择其他日期</div>
      </div>
    `;
    NewsState.newsTabInitialized = true;
    return;
  }
  
  newsTabList.innerHTML = '';
  
  // 按时间分组
  let currentDate = '';
  
  newsItems.forEach(item => {
    // 检查是否需要添加日期分组标题
    const itemDate = item.date || '';
    if (itemDate && itemDate !== currentDate) {
      currentDate = itemDate;
      const dateGroup = document.createElement('div');
      dateGroup.className = 'news-date-group';
      dateGroup.innerHTML = `<span class="news-date-label">${currentDate}</span>`;
      newsTabList.appendChild(dateGroup);
    }
    
    const div = document.createElement('div');
    div.innerHTML = createNewsItemHTML(item);
    while (div.firstChild) {
      newsTabList.appendChild(div.firstChild);
    }
  });
  
  NewsState.newsTabInitialized = true;
  console.log('[news_v2] News tab rendered:', newsItems.length, 'items');
}

/**
 * 主加载函数：根据上下文决定加载策略
 * @param {boolean} forceFullDay - 强制全量加载（新闻 Tab 打开时）
 */
async function loadNews(forceFullDay = false) {
  const isFullDay = forceFullDay || !NewsState.sidebarInitialized;
  
  const newsItems = await fetchNewsData(isFullDay);
  if (newsItems.length === 0) {
    return;
  }
  
  // 总是更新侧边栏
  renderSidebarNews(newsItems, isFullDay && !NewsState.sidebarInitialized);
  NewsState.sidebarInitialized = true;
  
  // 如果强制全量，同时更新新闻 Tab
  if (forceFullDay) {
    renderNewsTab(newsItems);
  }
}

// ==================== 盘前分析/复盘 ====================

async function loadPremarketAndReview(dateStr) {
  const container = document.getElementById('premarketCards');
  if (!container) return;
  container.innerHTML = '';

  // 显示加载状态
  container.innerHTML = `
    <div class="premarket-loading">
      <div class="premarket-loading-spinner"></div>
      <span>正在加载盘前分析...</span>
    </div>
  `;

  // 获取盘前报告
  let preData = null;
  try {
    const url = dateStr
      ? `/api/premarket/report?date=${dateStr}`
      : '/api/premarket/latest';
    const res = await fetch(url);
    if (res.ok) {
      preData = await res.json();
    }
  } catch(e) {
    console.warn('premarket load failed:', e);
  }

  if (!preData || !preData.date) {
    container.innerHTML = `
      <div class="premarket-empty">
        <div class="premarket-empty-icon">📊</div>
        <div class="premarket-empty-title">暂无盘前分析</div>
        <div class="premarket-empty-desc">请等待明日 08:30 后查看最新分析</div>
      </div>
    `;
    return;
  }

  container.innerHTML = '';

  // 渲染盘前分析卡片
  const card = document.createElement('div');
  card.className = 'premarket-card';

  const rec = preData.recommended_sector || {};
  const stocks = preData.recommended_stocks || [];
  const topStock = stocks.length > 0 ? stocks[0] : null;

  // 三层筛选数据
  const allStocks = preData.all_stocks || [];
  const candidateStocks = preData.candidate_stocks || [];
  const finalStocks = preData.final_stocks || [];
  const allStocksCount = preData.all_stocks_count || allStocks.length;
  const candidateStocksCount = preData.candidate_stocks_count || candidateStocks.length;
  const finalStocksCount = preData.final_stocks_count || finalStocks.length;
  const chipReadyCount = preData.chip_ready_count || 0;

  // 生成股票标签HTML
  function renderStockTags(stockList) {
    if (!stockList || stockList.length === 0) {
      return '<span class="premarket-empty-tags">暂无数据</span>';
    }
    return stockList.map(s => `
      <span class="premarket-stock-tag">
        ${s.name || s.symbol || '-'} <span class="premarket-stock-tag-change" style="color:${colorPct(s.change_pct)};">${formatPct(s.change_pct)}</span>
      </span>
    `).join('');
  }

  card.innerHTML = `
    <div class="premarket-card-header">
      <div class="premarket-card-title">
        <span class="premarket-icon">📅</span>
        <span>${preData.date} 盘前分析</span>
      </div>
      <span class="premarket-badge">推荐板块</span>
    </div>
    <div class="premarket-card-body">
      <div class="premarket-main-info">
        <div class="premarket-sector-name">
          ${rec.name || '-'}
          <span class="premarket-sector-code">${rec.code || ''}</span>
        </div>
        <div class="premarket-sector-change" style="color:${colorPct(rec.change_pct)};">
          ${formatPct(rec.change_pct)}
        </div>
        <div class="premarket-sector-logic">
          ${rec.logic || ''}
        </div>
        ${topStock ? `
        <div class="premarket-top-stock">
          <span class="premarket-top-stock-label">🏆 领涨股</span>
          <span class="premarket-top-stock-name">${topStock.name}</span>
          <span class="premarket-top-stock-change" style="color:${colorPct(topStock.change_pct)};">${formatPct(topStock.change_pct)}</span>
        </div>` : ''}
        
        <!-- 三层筛选摘要 -->
        <div class="premarket-filter-summary">
          <div class="premarket-filter-item">
            <span class="premarket-filter-label">全量成分股</span>
            <span class="premarket-filter-count">${allStocksCount}</span>
          </div>
          <div class="premarket-filter-arrow">→</div>
          <div class="premarket-filter-item">
            <span class="premarket-filter-label">基础筛选</span>
            <span class="premarket-filter-count">${candidateStocksCount}</span>
          </div>
          <div class="premarket-filter-arrow">→</div>
          <div class="premarket-filter-item">
            <span class="premarket-filter-label">最终筛选</span>
            <span class="premarket-filter-count premarket-filter-count-final">${finalStocksCount}</span>
          </div>
        </div>
        ${chipReadyCount > 0 ? `<div class="premarket-chip-info">💎 筹码就绪: ${chipReadyCount} 只</div>` : ''}
      </div>
      <div class="premarket-toggle-wrap">
        <button id="premarketToggleBtn" class="premarket-toggle-btn">
          📋 展开详情
        </button>
      </div>
    </div>
    <div id="premarketDetails" class="premarket-details" style="display:none;">
      <!-- 三层筛选详情 -->
      <div class="premarket-filter-sections">
        <!-- 全量成分股 -->
        <div class="premarket-filter-section">
          <div class="premarket-filter-section-header">
            <span class="premarket-filter-section-title">📊 全量成分股</span>
            <span class="premarket-filter-section-count">${allStocksCount} 只</span>
          </div>
          <div class="premarket-stocks-list">
            ${renderStockTags(allStocks)}
          </div>
        </div>
        
        <!-- 基础筛选后 -->
        <div class="premarket-filter-section">
          <div class="premarket-filter-section-header">
            <span class="premarket-filter-section-title">🔍 基础筛选后</span>
            <span class="premarket-filter-section-count">${candidateStocksCount} 只</span>
          </div>
          <div class="premarket-stocks-list">
            ${renderStockTags(candidateStocks)}
          </div>
        </div>
        
        <!-- 最终筛选后 -->
        <div class="premarket-filter-section">
          <div class="premarket-filter-section-header">
            <span class="premarket-filter-section-title">✅ 最终筛选后</span>
            <span class="premarket-filter-section-count premarket-filter-section-count-final">${finalStocksCount} 只</span>
          </div>
          <div class="premarket-stocks-list">
            ${renderStockTags(finalStocks)}
          </div>
        </div>
      </div>
      
      ${stocks.length > 0 ? `
      <div class="premarket-stocks-section">
        <div class="premarket-stocks-title">推荐成分股 TOP ${stocks.length}</div>
        <div class="premarket-stocks-list">
          ${stocks.map(s => `
            <span class="premarket-stock-tag">
              ${s.name} <span class="premarket-stock-tag-change" style="color:${colorPct(s.change_pct)};">${formatPct(s.change_pct)}</span>
            </span>
          `).join('')}
        </div>
      </div>` : ''}
      ${preData.llm_analysis ? renderStructuredLLMAnalysis(preData.llm_analysis) : ''}
    </div>
  `;
  container.appendChild(card);

  // 展开/折叠
  const toggleBtn = document.getElementById('premarketToggleBtn');
  const details = document.getElementById('premarketDetails');
  if (toggleBtn && details) {
    toggleBtn.onclick = function() {
      const show = details.style.display === 'none';
      details.style.display = show ? 'block' : 'none';
      toggleBtn.textContent = show ? '📋 收起详情' : '📋 展开详情';
    };
  }

  // ==================== 复盘分析 ====================
  await loadReviewData(dateStr || preData?.date);
}

/**
 * 加载并渲染复盘数据
 */
async function loadReviewData(dateStr) {
  const reviewContainer = document.getElementById('reviewCards');
  const reviewSection = document.getElementById('reviewSection');
  
  if (!reviewContainer) return;
  
  // 显示加载状态
  reviewContainer.innerHTML = `
    <div class="review-loading">
      <div class="review-loading-spinner"></div>
      <span>正在加载复盘分析...</span>
    </div>
  `;
  if (reviewSection) {
    reviewSection.style.display = 'block';
  }

  // 获取复盘报告
  let reviewData = null;
  try {
    const url = dateStr
      ? `/api/review/report?date=${dateStr}`
      : '/api/review/latest';
    const rres = await fetch(url);
    if (rres.ok) {
      reviewData = await rres.json();
    }
  } catch(e) {
    console.warn('review load failed:', e);
  }

  if (!reviewData || (!reviewData.prediction && !reviewData.recommendation_snapshot)) {
    reviewContainer.innerHTML = `
      <div class="review-empty">
        <div class="review-empty-icon">🔄</div>
        <div class="review-empty-title">暂无复盘分析</div>
        <div class="review-empty-desc">请等待收盘后查看最新复盘</div>
      </div>
    `;
    return;
  }

  reviewContainer.innerHTML = '';

  // 渲染复盘分析卡片
  const reviewCard = document.createElement('div');
  reviewCard.className = 'review-card';

  // 支持两种数据结构：旧版 prediction 和 新版 recommendation_snapshot
  const pred = reviewData.prediction || reviewData.recommendation_snapshot || {};
  const actual = reviewData.actual || {};
  const evalData = reviewData.evaluation || {};

  const actualColor = actual.sector_change_pct > 0 ? '#22c55e' : actual.sector_change_pct < 0 ? '#ef4444' : 'var(--muted,#9aa5ce)';
  
  // 兼容两种字段名：旧版 predicted_change 和 新版 entry_change_pct
  const predictedChange = pred.predicted_change !== undefined ? pred.predicted_change : pred.entry_change_pct;

  reviewCard.innerHTML = `
    <div class="review-card-header">
      <div class="review-card-title">
        <span class="review-icon">🔄</span>
        <span>${reviewData.date || dateStr || ''} 盘后复盘</span>
      </div>
      <span class="review-badge">复盘分析</span>
    </div>
    <div class="review-comparison">
      <div class="review-prediction-box">
        <div class="review-box-label">🔮 预测板块</div>
        <div class="review-sector-name">${pred.sector_name || '-'}</div>
        <div class="review-predicted-change">${formatPct(predictedChange)}</div>
        <div class="review-prediction-logic">${pred.logic || ''}</div>
      </div>
      <div class="review-actual-box">
        <div class="review-box-label">📊 实际板块</div>
        <div class="review-actual-change" style="color:${actualColor};">${formatPct(actual.sector_change_pct)}</div>
        ${actual.best_stock ? `
        <div class="review-best-stock">
          <span>🏆 最佳</span>
          <span style="color:#22c55e;">${actual.best_stock.name} ${formatPct(actual.best_stock.change_pct)}</span>
        </div>` : ''}
        ${actual.worst_stock ? `
        <div class="review-worst-stock">
          <span>📉 最差</span>
          <span style="color:#ef4444;">${actual.worst_stock.name} ${formatPct(actual.worst_stock.change_pct)}</span>
        </div>` : ''}
      </div>
    </div>
    <div class="review-verdict">
      <span class="review-verdict-icon">${evalData.direction_correct ? '✅' : '❌'}</span>
      <span class="review-verdict-text">${evalData.verdict || '-'}</span>
      <span class="review-verdict-diff">偏差 ${evalData.abs_diff !== undefined ? Number(evalData.abs_diff).toFixed(2) + '%' : '-'}</span>
    </div>
    ${reviewData.llm_review ? renderStructuredReview(reviewData.llm_review) : ''}
  `;
  reviewContainer.appendChild(reviewCard);
}

// ==================== 采集器状态 ====================

async function updateCollectorStatus() {
  try {
    const res = await fetch('/api/news/status');
    const data = await res.json();
    
    // 更新状态栏
    const collectorDot = document.getElementById('statusBarCollectorDot');
    const collectorText = document.getElementById('statusBarCollectorText');
    const newsCount = document.getElementById('statusBarNewsCount');
    
    if (collectorDot && collectorText && newsCount) {
      if (data.collector_running) {
        collectorDot.classList.remove('stopped');
        collectorText.textContent = '采集中';
      } else {
        collectorDot.classList.add('stopped');
        collectorText.textContent = '已停止';
      }
      newsCount.textContent = `${data.news_count || 0}条`;
    }
  } catch(e) {
    console.warn('collector status check failed:', e);
  }
}

// ==================== 日期选择器 ====================

/**
 * 获取持久化的日期，若无则返回今天
 */
function getPersistedDate() {
  const stored = localStorage.getItem(STOCK_UI_DATE_KEY);
  if (stored && stored.match(/^\d{4}-\d{2}-\d{2}$/)) {
    return stored;
  }
  return new Date().toISOString().slice(0, 10);
}

/**
 * 持久化日期选择
 */
function persistDate(dateStr) {
  if (dateStr && dateStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
    localStorage.setItem(STOCK_UI_DATE_KEY, dateStr);
  }
}

/**
 * 同步其他日期输入框（analysis.js / review.js）
 */
function syncDateInputsToDate(dateStr) {
  const analysisInput = document.getElementById('analysisDateInput');
  const reviewInput = document.getElementById('reviewDateInput');
  if (analysisInput) analysisInput.value = dateStr;
  if (reviewInput) reviewInput.value = dateStr;
}

function initNewsDateSelector() {
  const input = document.getElementById('newsDateInput');
  if (!input) {
    console.warn('newsDateInput not found');
    return;
  }
  
  // 从 localStorage 恢复日期，若无则默认今天
  NewsState.currentDate = getPersistedDate();
  input.value = NewsState.currentDate;
  
  // 同步其他面板的日期输入
  syncDateInputsToDate(NewsState.currentDate);
  
  input.addEventListener('change', function() {
    const dateStr = input.value;
    NewsState.currentDate = dateStr;
    NewsState.lastNewsTime = '';  // 重置游标
    
    // 持久化日期选择
    persistDate(dateStr);
    
    // 同步其他面板的日期输入
    syncDateInputsToDate(dateStr);
    
    // 日期变化时联动刷新：新闻列表 + 盘前分析 + 盘后复盘
    loadNews(true);
    loadPremarketAndReview(dateStr);
    loadReviewData(dateStr);
  });
}

// ==================== Tab 切换集成 ====================

/**
 * 新闻 Tab 激活时调用 - 强制全量加载
 */
function onNewsTabActivate() {
  console.log('[news_v2] News tab activated, loading full day news');
  loadNews(true);
  loadPremarketAndReview(NewsState.currentDate);
}

// ==================== 初始化 ====================

function initNewsSystem() {
  console.log('[news_v2] Initializing news system...');
  
  try {
    // 1. 初始化日期选择器
    initNewsDateSelector();
    
    // 2. 初始加载（侧边栏 + 预加载新闻 Tab 数据）
    loadNews(true);
    
    // 3. 加载盘前分析
    loadPremarketAndReview();
    
    // 4. 更新采集器状态
    updateCollectorStatus();
    
    // 5. 设置定时刷新（侧边栏增量）
    setInterval(function() {
      loadNews(false);
    }, NewsState.refreshInterval);
    
    // 6. 定时更新采集器状态
    setInterval(function() {
      updateCollectorStatus();
    }, 60000);
    
    console.log('[news_v2] News system initialized successfully');
  } catch(e) {
    console.error('[news_v2] Initialization failed:', e);
  }
}

// ==================== 结构化渲染复盘分析 ====================

/**
 * 渲染复盘分析的 Markdown 内容
 * 将简单的 Markdown 转换为 HTML
 */
function renderStructuredReview(reviewText) {
  if (!reviewText || reviewText.trim().length === 0) return '';
  
  // 简单的 Markdown 解析
  let html = reviewText
    // 标题
    .replace(/^📊\s*\*\*(.+?)\*\*$/gm, '<div style="font-size:15px; font-weight:700; color:var(--text); margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border);">📊 $1</div>')
    // 小标题
    .replace(/^💰\s*\*\*(.+?)\*\*$/gm, '<div style="font-size:13px; font-weight:600; color:var(--text-secondary); margin:14px 0 8px 0;">💰 $1</div>')
    .replace(/^📰\s*\*\*(.+?)\*\*$/gm, '<div style="font-size:13px; font-weight:600; color:var(--text-secondary); margin:14px 0 8px 0;">📰 $1</div>')
    .replace(/^💡\s*\*\*(.+?)\*\*$/gm, '<div style="font-size:13px; font-weight:600; color:var(--text-secondary); margin:14px 0 8px 0;">💡 $1</div>')
    // 加粗
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--text);">$1</strong>')
    // 换行
    .replace(/\n/g, '<br>');
  
  return `
    <div class="review-ai-section">
      <div class="review-ai-title">🤖 AI 复盘</div>
      <div class="review-ai-content" style="font-size:13px; color:var(--text-secondary); line-height:1.8;">${html}</div>
    </div>
  `;
}

// ==================== 结构化渲染 LLM 分析 ====================

/**
 * 将 LLM 分析文本结构化为 HTML
 * 解析格式：宏观形势判断、推荐板块、推荐理由、关键催化、相关新闻、风险提示
 */
function renderStructuredLLMAnalysis(llmText) {
  if (!llmText || llmText.trim().length === 0) return '';
  
  // 解析各个段落
  const sections = parseLLMAnalysisSections(llmText);
  
  let html = '<div class="premarket-ai-structured">';
  html += '<div class="premarket-ai-structured-title">🤖 AI 盘前分析</div>';
  
  // 宏观形势判断
  if (sections.macro) {
    html += `
      <div class="premarket-ai-section">
        <div class="premarket-ai-section-title">📊 宏观形势判断</div>
        <div class="premarket-ai-section-content">${escapeHtml(sections.macro)}</div>
      </div>
    `;
  }
  
  // 推荐板块
  if (sections.sector) {
    html += `
      <div class="premarket-ai-section">
        <div class="premarket-ai-section-title">🎯 推荐板块</div>
        <div class="premarket-ai-section-content">${escapeHtml(sections.sector)}</div>
      </div>
    `;
  }
  
  // 推荐理由
  if (sections.reason) {
    html += `
      <div class="premarket-ai-section">
        <div class="premarket-ai-section-title">💡 推荐理由</div>
        <div class="premarket-ai-section-content">${escapeHtml(sections.reason)}</div>
      </div>
    `;
  }
  
  // 关键催化
  if (sections.catalyst) {
    html += `
      <div class="premarket-ai-section">
        <div class="premarket-ai-section-title">⚡ 关键催化</div>
        <div class="premarket-ai-section-content">${escapeHtml(sections.catalyst)}</div>
      </div>
    `;
  }
  
  // 相关新闻 - 特别处理，保留完整列表
  if (sections.news && sections.news.length > 0) {
    html += `
      <div class="premarket-ai-section">
        <div class="premarket-ai-section-title">📰 相关新闻 (${sections.news.length} 条)</div>
        <div class="premarket-ai-news-list">
          ${sections.news.map(news => `<div class="premarket-ai-news-item">${escapeHtml(news)}</div>`).join('')}
        </div>
      </div>
    `;
  }
  
  // 风险提示
  if (sections.risk) {
    html += `
      <div class="premarket-ai-section premarket-ai-risk">
        <div class="premarket-ai-section-title">⚠️ 风险提示</div>
        <div class="premarket-ai-section-content">${escapeHtml(sections.risk)}</div>
      </div>
    `;
  }
  
  // 如果没有解析出结构化内容，显示原始文本
  if (!sections.macro && !sections.sector && !sections.reason && !sections.catalyst && sections.news.length === 0 && !sections.risk) {
    html += `
      <div class="premarket-ai-section">
        <div class="premarket-ai-section-content premarket-ai-raw">${escapeHtml(llmText)}</div>
      </div>
    `;
  }
  
  html += '</div>';
  return html;
}

/**
 * 解析 LLM 分析文本为结构化段落
 */
function parseLLMAnalysisSections(text) {
  const sections = {
    macro: '',
    sector: '',
    reason: '',
    catalyst: '',
    news: [],
    risk: ''
  };
  
  if (!text) return sections;
  
  // 宏观形势判断（支持中英文冒号）
  const macroMatch = text.match(/宏观形势判断[:：]\s*([\s\S]*?)(?=推荐板块[:：]|$)/i);
  if (macroMatch) sections.macro = macroMatch[1].trim();
  
  // 推荐板块（支持中英文冒号）
  const sectorMatch = text.match(/推荐板块[:：]\s*([\s\S]*?)(?=推荐理由[:：]|$)/i);
  if (sectorMatch) sections.sector = sectorMatch[1].trim();
  
  // 推荐理由（支持中英文冒号）
  const reasonMatch = text.match(/推荐理由[:：]\s*([\s\S]*?)(?=关键催化[:：]|$)/i);
  if (reasonMatch) sections.reason = reasonMatch[1].trim();
  
  // 关键催化（支持中英文冒号）
  const catalystMatch = text.match(/关键催化[:：]\s*([\s\S]*?)(?=相关新闻[:：]|$)/i);
  if (catalystMatch) sections.catalyst = catalystMatch[1].trim();
  
  // 相关新闻 - 提取所有新闻条目（支持中英文冒号）
  const newsMatch = text.match(/相关新闻[:：]\s*([\s\S]*?)(?=风险提示[:：]|$)/i);
  if (newsMatch) {
    const newsText = newsMatch[1].trim();
    // 按行分割，过滤空行
    const lines = newsText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    sections.news = lines;
  }
  
  // 风险提示（支持中英文冒号）
  const riskMatch = text.match(/风险提示[:：]\s*([\s\S]*?)$/i);
  if (riskMatch) sections.risk = riskMatch[1].trim();
  
  return sections;
}

/**
 * HTML 转义
 */
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ==================== 导出到 window（供 main.js 调用） ====================

window.NewsState = NewsState;
window.loadNews = loadNews;
window.onNewsTabActivate = onNewsTabActivate;
window.loadPremarketAndReview = loadPremarketAndReview;
window.updateCollectorStatus = updateCollectorStatus;

// 自动初始化（DOM 就绪后）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initNewsSystem);
} else {
  initNewsSystem();
}

console.log('[news_v2.js] Loaded successfully');
