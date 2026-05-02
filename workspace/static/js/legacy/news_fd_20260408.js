// news.js - 新闻直播函数 + 盘前分析 + 复盘查看
// Updated: 2026-03-26 - Added premarket analysis & review

var lastNewsTime = '';

// ==================== 采集器状态 ====================

async function updateCollectorStatus() {
  try {
    const res = await fetch('/api/news/status');
    const data = await res.json();
    const dot = document.getElementById('collectorStatusDot');
    const text = document.getElementById('collectorStatusText');
    if (!dot || !text) return;
    
    if (data.collector_running) {
      dot.style.background = '#22c55e';
      text.textContent = '采集中';
    } else {
      dot.style.background = '#ef4444';
      text.textContent = '已停止';
    }
    
    // 在 newsBody 底部显示采集统计
    const newsBody = document.getElementById('newsBody');
    let statsDiv = document.getElementById('collectorStats');
    if (newsBody && !statsDiv) {
      statsDiv = document.createElement('div');
      statsDiv.id = 'collectorStats';
      statsDiv.style.cssText = 'margin-top:10px; padding-top:10px; border-top:1px solid var(--border,#1f2937); font-size:11px; color:var(--muted,#9aa5ce);';
      newsBody.appendChild(statsDiv);
    }
    if (statsDiv) statsDiv.textContent = `采集统计：新闻总数 ${data.news_count || 0}`;
  } catch(e) {
    console.warn('collector status check failed:', e);
  }
}

window.updateCollectorStatus = updateCollectorStatus;

// ==================== 新闻加载 ====================

async function loadRecentNews(isFirst = false, forceFullDay = false, renderFullscreen = false) {
  // 首次加载：获取当天全量新闻（limit=5000）；后续轮询：仅获取新增（limit=20）
  const limit = isFirst && (forceFullDay || !lastNewsTime) ? 5000 : 20;
  const afterParam = !forceFullDay && lastNewsTime ? `&after=${encodeURIComponent(lastNewsTime)}` : '';
  const url = `/api/news/recent?date=today&limit=${limit}${afterParam}`;
  try {
    const res = await fetch(url);
    const data = await res.json();
    if (!data.news || data.news.length === 0) return;
    if (data.last_time) lastNewsTime = data.last_time;

    // 渲染到侧边栏新闻列表（监控 Tab）
    const sidebarList = document.getElementById('newsList');
    if (sidebarList && sidebarList.closest('#tabContentMonitor')) {
      // 如果是首次加载或强制全量，先清空侧边栏
      if (isFirst && (forceFullDay || !lastNewsTime)) {
        sidebarList.innerHTML = '';
      }
      data.news.forEach(item => {
        const div = document.createElement('div');
        div.style.cssText = 'padding:10px; background:var(--bg-card,rgba(255,255,255,0.03)); border-radius:8px; border-left:3px solid #6366f1;';
        div.innerHTML = '<div style="font-size:11px; color:var(--muted,#9aa5ce); margin-bottom:4px;">' + item.time + ' · ' + (item.source || '') + '</div><div style="font-size:13px; color:var(--text,#d1d4dc); font-weight:600; margin-bottom:4px;">' + item.title + '</div><div style="font-size:12px; color:var(--muted,#9aa5ce); line-height:1.5;">' + (item.summary || '') + '</div>';
        sidebarList.insertBefore(div, sidebarList.firstChild);
      });
      while (sidebarList.children.length > 20) sidebarList.removeChild(sidebarList.lastChild);
    }

    // 渲染到新闻 Tab 全屏列表
    const fullscreenList = document.querySelector('#tabContentNews #newsList');
    if (fullscreenList && (isFirst || renderFullscreen)) {
      // 强制全量加载时，清空并重新渲染
      if (forceFullDay || !lastNewsTime) {
        fullscreenList.innerHTML = '';
        data.news.forEach(item => {
          const div = document.createElement('div');
          div.className = 'news-item-fullscreen';
          div.innerHTML = `
            <div class="news-time-fullscreen">${item.time} · ${item.source || ''}</div>
            <div class="news-title-fullscreen">${item.title}</div>
            <div class="news-summary-fullscreen">${item.summary || ''}</div>
          `;
          fullscreenList.appendChild(div);
        });
      }
    }
  } catch(e) {
    console.warn('news load failed:', e);
  }
}

// ==================== 盘前分析 ====================

function getSelectedNewsDate() {
  const input = document.getElementById('newsDateInput');
  return input ? input.value : '';
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

async function loadPremarketAndReview(dateStr) {
  const container = document.getElementById('premarketCards');
  if (!container) return;
  container.innerHTML = '';

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
    container.innerHTML = '<div style="color:var(--muted,#9aa5ce); font-size:13px; padding:20px 0; text-align:center;">暂无盘前分析，请等待明日 08:30</div>';
    return;
  }

  // 渲染盘前分析卡片
  const card = document.createElement('div');
  card.style.cssText = 'background:var(--bg-card,rgba(255,255,255,0.03)); border-radius:10px; padding:16px; border:1px solid var(--border,#1f2937);';

  const rec = preData.recommended_sector || {};
  const stocks = preData.recommended_stocks || [];
  const topStock = stocks.length > 0 ? stocks[0] : null;

  card.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <div style="font-size:15px; font-weight:600;">📅 ${preData.date} 盘前分析</div>
      <div style="font-size:12px; color:var(--muted,#9aa5ce);">推荐板块</div>
    </div>
    <div style="display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap;">
      <div style="flex:1; min-width:200px;">
        <div style="font-size:20px; font-weight:700; margin-bottom:4px;">
          ${rec.name || '-'}
          <span style="font-size:13px; color:var(--muted,#9aa5ce); font-weight:400; margin-left:6px;">${rec.code || ''}</span>
        </div>
        <div style="font-size:18px; font-weight:600; color:${colorPct(rec.change_pct)}; margin-bottom:8px;">
          ${formatPct(rec.change_pct)}
        </div>
        <div style="font-size:12px; color:var(--muted,#9aa5ce); line-height:1.6; margin-bottom:8px;">
          ${rec.logic || ''}
        </div>
        ${topStock ? `
        <div style="font-size:12px; color:var(--text,#d1d4dc);">
          🏆 领涨股：<span style="font-weight:600;">${topStock.name}</span>
          <span style="color:${colorPct(topStock.change_pct)}; margin-left:4px;">${formatPct(topStock.change_pct)}</span>
        </div>` : ''}
      </div>
      <div style="flex:0 0 auto;">
        <button id="premarketToggleBtn" style="background:var(--bg-card,rgba(255,255,255,0.06)); border:1px solid var(--border,#1f2937); color:var(--text,#d1d4dc); padding:6px 14px; border-radius:6px; cursor:pointer; font-size:12px;">
          📋 展开详情
        </button>
      </div>
    </div>
    <div id="premarketDetails" style="display:none; margin-top:14px; padding-top:14px; border-top:1px solid var(--border,#1f2937);">
      <!-- 推荐成分股 TOP 10 -->
      ${stocks.length > 0 ? `
      <div style="margin-bottom:12px;">
        <div style="font-size:13px; font-weight:600; margin-bottom:8px;">推荐成分股 TOP ${stocks.length}</div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;">
          ${stocks.map(s => `
            <span style="background:rgba(41,98,255,0.1); border:1px solid rgba(41,98,255,0.2); padding:4px 10px; border-radius:6px; font-size:12px; white-space:nowrap;">
              ${s.name} <span style="color:${colorPct(s.change_pct)}; font-weight:600;">${formatPct(s.change_pct)}</span>
            </span>
          `).join('')}
        </div>
      </div>` : ''}
      <!-- LLM 分析 -->
      ${preData.llm_analysis ? `
      <div>
        <div style="font-size:13px; font-weight:600; margin-bottom:6px;">🤖 AI 分析</div>
        <div style="font-size:12px; color:var(--muted,#9aa5ce); line-height:1.8; white-space:pre-wrap;">${preData.llm_analysis}</div>
      </div>` : ''}
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
  let reviewData = null;
  try {
    const dateParam = dateStr || preData.date;
    const rres = await fetch(`/api/review/report?date=${dateParam}`);
    if (rres.ok) {
      reviewData = await rres.json();
    }
  } catch(e) {
    console.warn('review load failed:', e);
  }

  if (reviewData && reviewData.prediction) {
    const reviewCard = document.createElement('div');
    reviewCard.style.cssText = 'background:var(--bg-card,rgba(255,255,255,0.03)); border-radius:10px; padding:16px; border:1px solid var(--border,#1f2937); margin-top:12px;';

    const pred = reviewData.prediction || {};
    const actual = reviewData.actual || {};
    const evalData = reviewData.evaluation || {};

    const actualColor = actual.sector_change_pct > 0 ? '#22c55e' : actual.sector_change_pct < 0 ? '#ef4444' : 'var(--muted,#9aa5ce)';

    reviewCard.innerHTML = `
      <div style="font-size:15px; font-weight:600; margin-bottom:12px;">🔄 复盘分析</div>
      <!-- 预测 vs 实际 -->
      <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:14px;">
        <div style="flex:1; min-width:160px; background:rgba(41,98,255,0.08); border-radius:8px; padding:12px;">
          <div style="font-size:11px; color:var(--muted,#9aa5ce); margin-bottom:4px;">🔮 预测板块</div>
          <div style="font-size:14px; font-weight:600; margin-bottom:2px;">${pred.sector_name || '-'}</div>
          <div style="font-size:16px; font-weight:700; color:#6366f1;">${formatPct(pred.predicted_change)}</div>
          <div style="font-size:11px; color:var(--muted,#9aa5ce); margin-top:4px; line-height:1.5;">${pred.logic || ''}</div>
        </div>
        <div style="flex:1; min-width:160px; background:rgba(34,197,94,0.08); border-radius:8px; padding:12px;">
          <div style="font-size:11px; color:var(--muted,#9aa5ce); margin-bottom:4px;">📊 实际板块</div>
          <div style="font-size:16px; font-weight:700; color:${actualColor};">${formatPct(actual.sector_change_pct)}</div>
          ${actual.best_stock ? `
          <div style="font-size:12px; margin-top:6px;">
            🏆 最佳：<span style="color:#22c55e;">${actual.best_stock.name} ${formatPct(actual.best_stock.change_pct)}</span>
          </div>` : ''}
          ${actual.worst_stock ? `
          <div style="font-size:12px; margin-top:2px;">
            📉 最差：<span style="color:#ef4444;">${actual.worst_stock.name} ${formatPct(actual.worst_stock.change_pct)}</span>
          </div>` : ''}
        </div>
      </div>
      <!-- 评估结果 -->
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px; padding:8px 12px; background:rgba(255,255,255,0.03); border-radius:6px;">
        <span style="font-size:14px;">${evalData.direction_correct ? '✅' : '❌'}</span>
        <span style="font-size:13px; font-weight:600;">${evalData.verdict || '-'}</span>
        <span style="font-size:12px; color:var(--muted,#9aa5ce); margin-left:auto;">偏差 ${evalData.abs_diff !== undefined ? Number(evalData.abs_diff).toFixed(2) + '%' : '-'}</span>
      </div>
      <!-- LLM 复盘 -->
      ${reviewData.llm_review ? `
      <div>
        <div style="font-size:13px; font-weight:600; margin-bottom:6px;">🤖 AI 复盘</div>
        <div style="font-size:12px; color:var(--muted,#9aa5ce); line-height:1.8; white-space:pre-wrap;">${reviewData.llm_review}</div>
      </div>` : ''}
    `;
    container.appendChild(reviewCard);
  }
}

// ==================== 新闻 Tab 日期选择 ====================

function initNewsDateSelector() {
  const input = document.getElementById('newsDateInput');
  if (!input) return;
  // 默认今天
  const today = new Date();
  const y = today.getFullYear();
  const m = String(today.getMonth() + 1).padStart(2, '0');
  const d = String(today.getDate()).padStart(2, '0');
  input.value = `${y}-${m}-${d}`;
  input.addEventListener('change', function() {
    loadPremarketAndReview(input.value);
    // 重新加载新闻
    lastNewsTime = '';
    loadRecentNews(true);
  });
}

// ==================== 初始化 ====================

function initNewsToggle() {
  const header = document.getElementById('newsHeader');
  const body = document.getElementById('newsBody');
  if (header && body) {
    header.style.cursor = 'pointer';
    header.onclick = function() {
      body.style.display = body.style.display === 'none' ? 'block' : 'none';
    };
  }
}

function initNewsTab() {
  initNewsToggle();
  initNewsDateSelector();
  // 首次加载全量新闻（但此时新闻 Tab 可能未激活，所以不渲染全屏列表）
  loadRecentNews(true, true, false);
  loadPremarketAndReview();
  updateCollectorStatus();
  setInterval(function() { loadRecentNews(false); }, 60000);
  setInterval(function() { updateCollectorStatus(); }, 60000);
}

function reloadNewsFullDay() {
  lastNewsTime = '';
  // 强制全量加载并渲染到全屏列表
  return loadRecentNews(true, true, true);
}

// 首次加载（DOM 加载完成后）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initNewsTab);
} else {
  initNewsTab();
}

// 暴露给外部调用（例如 tab 切换时刷新）
window.initNewsTab = initNewsTab;
window.loadRecentNews = loadRecentNews;
window.reloadNewsFullDay = reloadNewsFullDay;
window.loadPremarketAndReview = loadPremarketAndReview;
