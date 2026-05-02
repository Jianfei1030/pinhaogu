// main.js - 入口函数和 DOM 元素引用

// ===== 切换股票悬浮面板逻辑 =====
let symbolPanelOpen = false;

function toggleSymbolPanel() {
  const panel = document.getElementById('symbolPanel');
  const closeBtn = document.getElementById('symbolCloseBtn');
  const countEl = document.getElementById('symbolPanelCount');
  const container = document.getElementById('symbolListContainer');
  
  if (!panel) return;
  
  symbolPanelOpen = !symbolPanelOpen;
  
  if (symbolPanelOpen) {
    panel.hidden = false;
    renderSymbolList();
    
    // 绑定关闭按钮事件
    if (closeBtn && !closeBtn.dataset.bound) {
      closeBtn.addEventListener('click', () => {
        symbolPanelOpen = false;
        panel.hidden = true;
      });
      closeBtn.dataset.bound = 'true';
    }
  } else {
    panel.hidden = true;
  }
}

function renderSymbolList() {
  const container = document.getElementById('symbolListContainer');
  const countEl = document.getElementById('symbolPanelCount');
  if (!container) return;
  
  const watchlist = state.config?.watchlist || [];
  const currentSymbol = symbolSelect?.value || '';
  
  if (!watchlist.length) {
    container.innerHTML = '<div style="color:var(--muted, #9aa5ce); text-align:center; padding:20px;">暂无监控股票</div>';
    if (countEl) countEl.textContent = '0 只股票';
    return;
  }
  
  // 获取实时报价
  const html = watchlist.map((item, idx) => {
    const value = `${item.market}:${item.symbol}`;
    const quote = state.watchQuotes[item.symbol];
    const isActive = value === currentSymbol ? 'active' : '';
    
    let priceHtml = '<span style="color:var(--muted, #9aa5ce);">--</span>';
    let changeClass = 'flat';
    let changeText = '';
    
    if (quote && !quote.error) {
      const price = Number(quote.price || 0).toFixed(3);
      const changePct = Math.abs(quote.change_pct || 0).toFixed(2);
      const changeSymbol = quote.change >= 0 ? '↑' : '↓';
      changeClass = quote.change >= 0 ? 'up' : 'down';
      priceHtml = `<span class="symbol-price">${price}</span> <span class="symbol-change ${changeClass}">${changeSymbol}${changePct}%</span>`;
    }
    
    return `
      <div class="symbol-list-item ${isActive}" data-value="${value}" data-idx="${idx}">
        <div>
          <span class="symbol-code">${item.symbol}</span>
          <span class="symbol-name">${item.name || ''}</span>
        </div>
        <div>${priceHtml}</div>
      </div>
    `;
  }).join('');
  
  container.innerHTML = html;
  if (countEl) countEl.textContent = `${watchlist.length} 只股票`;
  
  // 绑定点击事件
  container.querySelectorAll('.symbol-list-item').forEach(item => {
    item.addEventListener('click', () => {
      const value = item.dataset.value;
      const idx = parseInt(item.dataset.idx, 10);
      
      // 更新 select
      if (symbolSelect) {
        symbolSelect.value = value;
        // 触发 change 事件（复用现有逻辑）
        symbolSelect.dispatchEvent(new Event('change'));
      }
      
      // 关闭面板
      symbolPanelOpen = false;
      const panel = document.getElementById('symbolPanel');
      if (panel) panel.hidden = true;
      
      // 高亮选中项
      highlightActiveWatch();
    });
  });
}

// ===== Tab 切换逻辑 =====
// 全局变量：当前 Tab
let currentTab = 'monitor';

function updateFloatingButtons(tabName) {
  // 「📊 盘前分析」按钮：只在新闻 Tab 激活时显示
  const analysisBtn = document.getElementById('analysisToggleBtn');
  if (analysisBtn) {
    analysisBtn.style.display = tabName === 'news' ? 'block' : 'none';
  }
  
  // 「📋 切换股票」按钮：只在监控 Tab 激活时显示
  const symbolBtn = document.getElementById('symbolToggleBtn');
  if (symbolBtn) {
    symbolBtn.style.display = tabName === 'monitor' ? 'block' : 'none';
  }
}

function initTabSwitcher() {
  const tabBar = document.getElementById('tabBar');
  if (!tabBar) return;
  
  tabBar.addEventListener('click', (e) => {
    const tabBtn = e.target.closest('.tab-btn');
    if (!tabBtn) return;
    
    const tabName = tabBtn.dataset.tab;
    if (!tabName) return;
    
    // 更新当前 Tab
    currentTab = tabName;
    
    // 更新 Tab 按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    tabBtn.classList.add('active');
    
    // 切换 Tab 内容
    document.querySelectorAll('.tab-content').forEach(content => {
      content.style.display = 'none';
    });
    
    const targetContent = document.getElementById('tabContent' + tabName.charAt(0).toUpperCase() + tabName.slice(1));
    if (targetContent) {
      targetContent.style.display = 'block';
    }
    
    // 控制悬浮按钮显隐
    updateFloatingButtons(tabName);

    // 切到新闻 Tab 时，强制重载当天全量新闻
    if (tabName === 'news') {
      if (typeof window.onNewsTabActivate === 'function') {
        window.onNewsTabActivate();
      } else if (typeof window.loadNews === 'function') {
        window.loadNews(true);
      }
    }
    
    // 如果是监控 Tab，重新渲染图表
    if (tabName === 'monitor' && state.current && state.current.kline && state.current.kline.length > 0) {
      requestAnimationFrame(() => {
        renderCharts();
      });
    }
  });
}

// ===== 常驻状态栏刷新 =====
function updateStatusBar() {
  const monitorDotEl = document.getElementById('statusBarMonitorDot');
  const monitorTextEl = document.getElementById('statusBarMonitorText');
  const stocksEl = document.getElementById('statusBarStocks');
  const collectorDotEl = document.getElementById('statusBarCollectorDot');
  const collectorTextEl = document.getElementById('statusBarCollectorText');
  const newsCountEl = document.getElementById('statusBarNewsCount');
  
  if (!stocksEl || !collectorDotEl || !collectorTextEl || !newsCountEl) return;
  
  // 更新 monitor 状态
  updateMonitorStatusInStatusBar(monitorDotEl, monitorTextEl);
  
  // 更新监控股票信息
  const watchlist = state.config?.watchlist || [];
  const stockTexts = [];
  for (const item of watchlist.slice(0, 5)) {
    const quote = state.watchQuotes[item.symbol];
    if (quote && !quote.error) {
      const changeSymbol = quote.change >= 0 ? '↑' : '↓';
      stockTexts.push(`${item.symbol} ${formatNum(quote.price)} ${changeSymbol}${Math.abs(quote.change_pct || 0).toFixed(2)}%`);
    } else if (quote && quote.error) {
      stockTexts.push(`${item.symbol} --`);
    }
  }
  stocksEl.textContent = stockTexts.join(' | ') || '加载中...';
  
  // 更新采集器状态
  updateCollectorStatusInStatusBar(collectorDotEl, collectorTextEl, newsCountEl);
  
  // 更新悬浮面板中的股票价格（如果面板打开）
  if (symbolPanelOpen) {
    updateSymbolPanelPrices();
  }
}

async function updateMonitorStatusInStatusBar(dotEl, textEl) {
  try {
    const res = await fetch('/api/monitor/status');
    const data = await res.json();
    
    // 1. 监控进程状态
    const monitorStatus = data.running ? '监控中' : '已停止';
    const monitorDot = data.running ? '🟢' : '🔴';
    
    // 2. 市场状态（基于当前北京时间判断是否在交易时段）
    const marketStatus = getMarketStatus();
    
    // 3. 合并展示
    dotEl.classList.remove('running', 'stopped');
    dotEl.classList.add(data.running ? 'running' : 'stopped');
    textEl.textContent = `${monitorDot} ${monitorStatus} · ${marketStatus}`;
  } catch(e) {
    console.warn('status bar monitor status check failed:', e);
    dotEl?.classList.remove('running');
    dotEl?.classList.add('stopped');
    textEl.textContent = '🔴 已停止 · 已收盘';
  }
}

// 判断当前是否在交易时段内
function getMarketStatus() {
  const now = new Date();
  const hour = now.getHours();
  const minute = now.getMinutes();
  const timeInMinutes = hour * 60 + minute;
  
  // 港股交易时段：09:00-16:10
  const hkStart = 9 * 60;      // 09:00
  const hkEnd = 16 * 60 + 10;  // 16:10
  
  // A 股交易时段：09:15-15:00（含午休 11:30-13:00）
  const aStart = 9 * 60 + 15;  // 09:15
  const aEnd = 15 * 60;        // 15:00
  const aLunchStart = 11 * 60 + 30;  // 11:30
  const aLunchEnd = 13 * 60;         // 13:00
  
  // 检查是否在港股交易时段
  const isHkTrading = timeInMinutes >= hkStart && timeInMinutes <= hkEnd;
  
  // 检查是否在 A 股交易时段（排除午休）
  const isATrading = (timeInMinutes >= aStart && timeInMinutes < aLunchStart) || 
                     (timeInMinutes > aLunchEnd && timeInMinutes <= aEnd);
  
  // 只要有一个市场在交易，就视为交易时段
  if (isHkTrading || isATrading) {
    return '交易中';
  } else {
    return '已收盘';
  }
}

async function updateCollectorStatusInStatusBar(dotEl, textEl, countEl) {
  try {
    const res = await fetch('/api/news/status');
    const data = await res.json();
    
    if (data.collector_running) {
      dotEl.classList.remove('stopped');
      textEl.textContent = '采集中';
    } else {
      dotEl.classList.add('stopped');
      textEl.textContent = '已停止';
    }
    
    countEl.textContent = `${data.news_count || 0}条`;
  } catch(e) {
    console.warn('status bar collector status check failed:', e);
  }
}

// DOM 元素引用（全局，供其他模块使用）
const symbolSelect = document.getElementById('symbolSelect');
const dateInput = document.getElementById('dateInput');
const periodSelect = document.getElementById('periodSelect');
const stockName = document.getElementById('stockName');
const stockMeta = document.getElementById('stockMeta');
const priceEl = document.getElementById('price');
const changeEl = document.getElementById('change');
const quoteTimeEl = document.getElementById('quoteTime');
const sourceBadgeEl = document.getElementById('sourceBadge');
const loadingEl = document.getElementById('loading');
const chartsEl = document.getElementById('charts');
const emptyEl = document.getElementById('empty');
const warningEl = document.getElementById('warning');
const tooltipEl = document.getElementById('tooltip');
const detailPanelEl = document.getElementById('detailPanel');
const detailTimeEl = document.getElementById('detailTime');
const detailOpenEl = document.getElementById('detailOpen');
const detailHighEl = document.getElementById('detailHigh');
const detailLowEl = document.getElementById('detailLow');
const detailCloseEl = document.getElementById('detailClose');
const detailVolumeEl = document.getElementById('detailVolume');
const detailDifEl = document.getElementById('detailDif');
const detailDeaEl = document.getElementById('detailDea');
const detailHistEl = document.getElementById('detailHist');
const klineCanvas = document.getElementById('klineCanvas');
const macdCanvas = document.getElementById('macdCanvas');
const watchListEl = document.getElementById('watchList');
const monitorStatusEl = document.getElementById('monitorStatus');
const refreshHintEl = document.getElementById('refreshHint');
const alertListEl = document.getElementById('alertList');
const addAlertBtn = document.getElementById('addAlertBtn');
const alertModalEl = document.getElementById('alertModal');
const modalTitleEl = document.getElementById('modalTitle');
const modalCloseEl = document.getElementById('modalClose');
const alertCancelBtn = document.getElementById('alertCancelBtn');
const alertSaveBtn = document.getElementById('alertSaveBtn');
const alertNameEl = document.getElementById('alertName');
const alertPeriodEl = document.getElementById('alertPeriod');
const alertConditionsEl = document.getElementById('alertConditions');
const addConditionBtn = document.getElementById('addConditionBtn');
const alertCooldownEl = document.getElementById('alertCooldown');
const alertLogicEl = document.getElementById('alertLogic');
const refreshSelect = document.getElementById('refreshSelect');
const historySelect = document.getElementById('analysisHistorySelect');
const newsStatusIcon = document.getElementById('newsStatusIcon');
const newsStatusText = document.getElementById('newsStatusText');
const newsStatusDiv = document.getElementById('newsStatus');

// 工具函数
function formatNum(value, digits = 3) {
  return Number(value || 0).toFixed(digits);
}

function formatPct(value) {
  const num = Number(value || 0);
  const sign = num > 0 ? '+' : '';
  return sign + num.toFixed(3) + '%';
}

function formatQuoteSource(source) {
  const mapping = {
    tencent: '腾讯',
    sina: '新浪',
    ths: '同花顺',
  };
  return mapping[String(source || '').toLowerCase()] || '';
}

function isThsSimSource(market, quote) {
  return String(market || '').toUpperCase() === 'HK' && String(quote?.source || '').toLowerCase() === 'ths';
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function clearDetailPanel() {
  detailPanelEl.style.display = 'none';
  detailTimeEl.textContent = '时间：--';
  detailOpenEl.textContent = '--';
  detailHighEl.textContent = '--';
  detailLowEl.textContent = '--';
  detailCloseEl.textContent = '--';
  detailVolumeEl.textContent = '--';
  detailDifEl.textContent = '--';
  detailDeaEl.textContent = '--';
  detailHistEl.textContent = '--';
}

function updateDetailPanel(index) {
  const kline = state.current?.kline || [];
  const macd = state.current?.macd || [];
  const bar = kline[index];
  if (!bar) {
    clearDetailPanel();
    return;
  }
  const macdRow = macd[index] || {};
  detailPanelEl.style.display = 'block';
  detailTimeEl.textContent = `时间：${bar.time || '--'}`;
  detailOpenEl.textContent = formatNum(bar.open);
  detailHighEl.textContent = formatNum(bar.high);
  detailLowEl.textContent = formatNum(bar.low);
  detailCloseEl.textContent = formatNum(bar.close);
  detailVolumeEl.textContent = Number(bar.volume || 0).toLocaleString('zh-CN');

  const difTrend = slopeArrow(macdRow.macd_slope);
  const deaTrend = slopeArrow(macdRow.dea_slope);
  const histTrend = slopeArrow(macdRow.hist_slope);
  detailDifEl.innerHTML = `${formatNum(macdRow.macd)} <span class="${difTrend.className}">(slope: ${difTrend.arrow})</span>`;
  detailDeaEl.innerHTML = `${formatNum(macdRow.dea)} <span class="${deaTrend.className}">(slope: ${deaTrend.arrow})</span>`;
  detailHistEl.innerHTML = `${formatNum(macdRow.hist)} <span class="${histTrend.className}">(slope: ${histTrend.arrow})</span>`;
}

function renderSummary() {
  const data = state.current;
  const list = data.kline || [];
  if (!list.length) {
    stockName.textContent = data.name || data.symbol;
    stockMeta.textContent = `${data.market}${data.symbol} · ${data.period} · ${data.date}`;
    priceEl.textContent = '-';
    priceEl.className = 'price';
    changeEl.textContent = '-';
    changeEl.className = 'change flat';
    quoteTimeEl.textContent = '数据时间：--';
    sourceBadgeEl.style.display = 'none';
    warningEl.style.display = 'none';
    clearDetailPanel();
    return;
  }

  const quote = state.currentQuote || {};
  const calibration = state.calibration || {};
  const quoteHasError = !!quote.error;
  const last = list[list.length - 1];
  
  // 判断是否为今天/最新交易日：如果是历史日期，使用 K 线数据而不是实时行情
  const isToday = data.date === state.today;
  const useRealtime = isToday && !quoteHasError;
  
  // 昨收：从 K 线倒数第二根读取（历史日期和今天都适用）
  let prevClose;
  if (list.length >= 2) {
    prevClose = Number(list[list.length - 2].close || 0);
  } else {
    prevClose = Number(data.prev_close || 0);
  }
  
  // 价格和涨跌幅：今天用实时行情，历史日期用 K 线数据
  let displayPrice, diff, pct;
  if (useRealtime) {
    // 今天：使用实时行情
    displayPrice = Number(quote.price || 0);
    diff = Number(quote.change || 0);
    pct = Number(quote.change_pct || 0);
  } else {
    // 历史日期：使用 K 线最后一根的收盘价，涨跌幅基于昨收计算
    displayPrice = Number(last.close || 0);
    diff = displayPrice - prevClose;
    pct = prevClose !== 0 ? (diff / prevClose * 100) : 0;
  }
  
  const quoteTime = quoteHasError ? '' : String(quote.time || '').trim();
  const quoteSource = quoteHasError ? '' : formatQuoteSource(quote.source);
  const calibrated = String(data.market || '').toUpperCase() === 'HK' && !!calibration.done;
  const thsSim = !calibrated && !quoteHasError && isThsSimSource(data.market, quote);

  stockName.textContent = quote.name || data.name || data.symbol;
  if (quoteHasError) {
    stockMeta.textContent = '请稍后刷新';
    priceEl.textContent = '⚠️ 数据暂不可用';
    priceEl.className = 'price error';
    changeEl.textContent = quote.error || '实时行情获取失败';
    changeEl.className = 'change error';
    quoteTimeEl.textContent = '数据时间：--';
    sourceBadgeEl.style.display = 'none';
    warningEl.style.display = 'none';
    return;
  }

  const metaMain = `${data.market}${data.symbol} · ${data.period} · ${data.date} · 收盘 ${formatNum(last.close)} · 昨收 ${formatNum(prevClose)}`;
  const sourceNote = calibrated
    ? '数据源：Tencent（已矫正）'
    : thsSim
      ? '数据源：THS-SIM（同花顺模拟 bar）'
      : '';
  stockMeta.innerHTML = sourceNote
    ? `${escapeHtml(metaMain)}<span class="source-note">${escapeHtml(sourceNote)}</span>`
    : escapeHtml(metaMain);
  priceEl.textContent = formatNum(displayPrice);
  priceEl.className = 'price';
  changeEl.textContent = `${diff >= 0 ? '+' : ''}${formatNum(diff)}  ${formatPct(pct)}`;
  changeEl.className = 'change ' + (diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat');
  sourceBadgeEl.style.display = (thsSim || calibrated) ? 'inline-flex' : 'none';
  sourceBadgeEl.textContent = calibrated ? 'Tencent（已矫正）' : 'THS-SIM（同花顺模拟 bar）';
  const timeMatch = quoteTime.match(/(\d{2}:\d{2})(?::\d{2})?$/);
  const timeLabel = timeMatch ? timeMatch[1] : (quoteTime || '--');
  quoteTimeEl.textContent = `🕐 ${timeLabel}${quoteSource ? ` ${quoteSource}` : ''}`;

  if (data.data_status !== 'ok') {
    warningEl.style.display = 'block';
    warningEl.textContent = `⚠️ 数据不足：当前 ${data.data_bars} 根 bar，建议 ≥ ${data.data_recommend_bars} 根；当前状态：${data.data_status}`;
  } else {
    warningEl.style.display = 'none';
  }
}

// ===== 侧栏抽屉触摸交互 =====
let sidebarOpen = false;
let sidebarTouchStartX = 0;
let sidebarTouchStartY = 0;
const SIDEBAR_SWIPE_THRESHOLD = 50;

function initSidebarDrawer() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  
  if (!sidebar || !backdrop) return;
  
  // 创建侧边栏切换按钮（移动端）
  createSidebarToggleBtn();
  
  // 点击遮罩层关闭侧栏
  backdrop.addEventListener('click', closeSidebar);
  
  // 触摸滑动关闭侧栏
  sidebar.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  sidebar.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  
  // 全局触摸检测（从屏幕左侧边缘滑动打开）
  document.addEventListener('touchstart', handleGlobalTouchStart, { passive: true });
  document.addEventListener('touchmove', handleGlobalTouchMove, { passive: true });
  document.addEventListener('touchend', handleGlobalTouchEnd, { passive: true });
}

function createSidebarToggleBtn() {
  // 检查是否已存在
  if (document.getElementById('sidebarToggleBtn')) return;
  
  const btn = document.createElement('button');
  btn.id = 'sidebarToggleBtn';
  btn.className = 'sidebar-toggle-btn';
  btn.innerHTML = '☰';
  btn.setAttribute('aria-label', '打开侧边栏');
  btn.style.display = 'none'; // 默认隐藏，在移动端显示
  
  btn.addEventListener('click', () => {
    if (sidebarOpen) {
      closeSidebar();
    } else {
      openSidebar();
    }
  });
  
  document.body.appendChild(btn);
  
  // 根据屏幕宽度决定是否显示按钮
  updateSidebarToggleVisibility();
  window.addEventListener('resize', updateSidebarToggleVisibility);
}

function updateSidebarToggleVisibility() {
  const btn = document.getElementById('sidebarToggleBtn');
  if (!btn) return;
  
  // 在小于 768px 的屏幕上显示切换按钮
  const isMobile = window.innerWidth <= 767;
  btn.style.display = isMobile ? 'flex' : 'none';
  
  // 桌面端确保侧栏始终可见
  if (!isMobile && sidebarOpen) {
    closeSidebar();
  }
}

function openSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  
  if (!sidebar || !backdrop) return;
  
  sidebarOpen = true;
  sidebar.classList.add('open');
  backdrop.classList.add('show');
  
  // 禁止背景滚动
  document.body.style.overflow = 'hidden';
  
  // 更新按钮状态
  const btn = document.getElementById('sidebarToggleBtn');
  if (btn) {
    btn.innerHTML = '✕';
    btn.setAttribute('aria-label', '关闭侧边栏');
  }
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  
  if (!sidebar || !backdrop) return;
  
  sidebarOpen = false;
  sidebar.classList.remove('open');
  backdrop.classList.remove('show');
  
  // 恢复背景滚动
  document.body.style.overflow = '';
  
  // 更新按钮状态
  const btn = document.getElementById('sidebarToggleBtn');
  if (btn) {
    btn.innerHTML = '☰';
    btn.setAttribute('aria-label', '打开侧边栏');
  }
}

function handleSidebarTouchStart(e) {
  if (!sidebarOpen) return;
  
  const touch = e.touches[0];
  sidebarTouchStartX = touch.clientX;
  sidebarTouchStartY = touch.clientY;
}

function handleSidebarTouchMove(e) {
  if (!sidebarOpen) return;
  
  const touch = e.touches[0];
  const deltaX = touch.clientX - sidebarTouchStartX;
  const deltaY = touch.clientY - sidebarTouchStartY;
  
  // 如果水平滑动距离大于垂直滑动，阻止默认行为
  if (Math.abs(deltaX) > Math.abs(deltaY) && deltaX < 0) {
    // 向左滑动，可以添加视觉反馈
  }
}

function handleSidebarTouchEnd(e) {
  if (!sidebarOpen) return;
  
  const touch = e.changedTouches[0];
  const deltaX = touch.clientX - sidebarTouchStartX;
  const deltaY = touch.clientY - sidebarTouchStartY;
  
  // 水平向左滑动超过阈值，关闭侧栏
  if (deltaX < -SIDEBAR_SWIPE_THRESHOLD && Math.abs(deltaX) > Math.abs(deltaY)) {
    closeSidebar();
  }
}

let globalTouchStartX = 0;
let globalTouchStartY = 0;
let globalTouchStartTime = 0;
const EDGE_SWIPE_ZONE = 30; // 屏幕左侧边缘区域宽度

function handleGlobalTouchStart(e) {
  // 只在监控 Tab 且移动端下响应
  if (currentTab !== 'monitor' || window.innerWidth > 767) return;
  
  const touch = e.touches[0];
  globalTouchStartX = touch.clientX;
  globalTouchStartY = touch.clientY;
  globalTouchStartTime = Date.now();
}

function handleGlobalTouchMove(e) {
  // 只在监控 Tab 且移动端下响应
  if (currentTab !== 'monitor' || window.innerWidth > 767) return;
  
  // 如果侧栏已打开，不处理
  if (sidebarOpen) return;
  
  // 检查是否从屏幕左侧边缘开始滑动
  if (globalTouchStartX > EDGE_SWIPE_ZONE) return;
  
  const touch = e.touches[0];
  const deltaX = touch.clientX - globalTouchStartX;
  const deltaY = touch.clientY - globalTouchStartY;
  
  // 如果水平向右滑动，阻止默认行为（避免页面滚动）
  if (deltaX > Math.abs(deltaY)) {
    // 可以在这里添加视觉反馈
  }
}

function handleGlobalTouchEnd(e) {
  // 只在监控 Tab 且移动端下响应
  if (currentTab !== 'monitor' || window.innerWidth > 767) return;
  
  // 如果侧栏已打开，不处理
  if (sidebarOpen) return;
  
  // 检查是否从屏幕左侧边缘开始滑动
  if (globalTouchStartX > EDGE_SWIPE_ZONE) return;
  
  const touch = e.changedTouches[0];
  const deltaX = touch.clientX - globalTouchStartX;
  const deltaY = touch.clientY - globalTouchStartY;
  const deltaTime = Date.now() - globalTouchStartTime;
  
  // 水平向右滑动超过阈值，且滑动时间不太长，打开侧栏
  if (deltaX > SIDEBAR_SWIPE_THRESHOLD && 
      Math.abs(deltaX) > Math.abs(deltaY) && 
      deltaTime < 300) {
    openSidebar();
  }
}

// 入口函数
async function init() {
  // 初始化 Tab 切换
  initTabSwitcher();
  
  // 初始化悬浮按钮显隐（根据默认 Tab）
  updateFloatingButtons(currentTab);
  
  // 初始化侧栏抽屉
  initSidebarDrawer();
  
  // 初始化切换股票悬浮按钮
  const symbolToggleBtn = document.getElementById('symbolToggleBtn');
  if (symbolToggleBtn) {
    symbolToggleBtn.addEventListener('click', toggleSymbolPanel);
  }
  
  // ★ 状态栏立即启动，不等任何东西
  updateStatusBar();
  setInterval(updateStatusBar, 10000);
  fetchMonitorStatus();
  setInterval(fetchMonitorStatus, 60000);
  
  // 新闻系统由 news_v2.js 自动初始化，无需手动调用
  
  const res = await fetch('/api/config');
  state.config = await res.json();
  const model = state.config.analysisModel || 'unknown';
  const modelLabel = document.getElementById('analysisModelLabel');
  if (modelLabel) {
    modelLabel.textContent = `${model} · 阿里百炼`;
  }
  buildControls();
  buildWatchSidebar();
  bindEvents();
  
  // 加载 K 线和告警数据
  await Promise.all([loadData(), loadAlerts()]);
  
  // 启动自动刷新
  startAutoRefresh();
}

function buildControls() {
  const watchlist = state.config.watchlist || [];
  symbolSelect.innerHTML = watchlist.map((item, idx) => {
    const value = `${item.market}:${item.symbol}`;
    return `<option value="${value}" ${idx === 0 ? 'selected' : ''}>${item.symbol} ${item.name || ''}</option>`;
  }).join('');

  const periods = Array.from(new Set([...(state.config.periods || ['5min', '15min', '30min', '60min']), 'daily']));
  const periodLabels = {
    '5min': '5 分钟',
    '15min': '15 分钟',
    '30min': '30 分钟',
    '60min': '60 分钟',
    'daily': '日线',
  };
  periodSelect.innerHTML = periods.map((period) => (`<option value="${period}" ${period === '15min' ? 'selected' : ''}>${periodLabels[period] || period}</option>`)).join('');
  dateInput.value = new Date().toISOString().slice(0, 10);
}

function getSelections() {
  const [market, symbol] = symbolSelect.value.split(':');
  return {
    market,
    symbol,
    period: periodSelect.value,
    date: dateInput.value,
  };
}

// 初始化执行
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => init().catch((err) => {
    console.error(err);
    setLoading(true, '初始化失败：' + err.message);
  }));
} else {
  init().catch((err) => {
    console.error(err);
    setLoading(true, '初始化失败：' + err.message);
  });
}
