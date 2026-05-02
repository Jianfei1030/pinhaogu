// review.js - 盘后复盘面板函数

(function() {
  const toggleBtn = document.getElementById('reviewToggleBtn');
  const panel = document.getElementById('reviewPanel');
  const closeBtn = document.getElementById('reviewCloseBtn');
  const runBtn = document.getElementById('reviewRunBtn');
  const dateInput = document.getElementById('reviewDateInput');
  const historySelect = document.getElementById('reviewHistorySelect');
  const progressCard = document.getElementById('reviewProgressCard');
  const progressBar = document.getElementById('reviewProgressBar');
  const statusText = document.getElementById('reviewStatusText');
  const metaText = document.getElementById('reviewMetaText');
  const resultEl = document.getElementById('reviewResult');

  // 使用全局持久化日期（localStorage），若无则今天
  const STOCK_UI_DATE_KEY = 'stock-ui-selected-date';
  const stored = localStorage.getItem(STOCK_UI_DATE_KEY);
  const defaultDate = stored && stored.match(/^\d{4}-\d{2}-\d{2}$/) ? stored : new Date().toISOString().slice(0, 10);
  dateInput.value = defaultDate;

  let isRestoring = false;

  // 监听日期变化，持久化并同步其他面板
  dateInput.addEventListener('change', function() {
    const dateStr = dateInput.value;
    if (dateStr && dateStr.match(/^\d{4}-\d{2}-\d{2}$/)) {
      localStorage.setItem(STOCK_UI_DATE_KEY, dateStr);
      // 同步其他日期输入
      const newsInput = document.getElementById('newsDateInput');
      const analysisInput = document.getElementById('analysisDateInput');
      if (newsInput) newsInput.value = dateStr;
      if (analysisInput) analysisInput.value = dateStr;
    }
  });

  toggleBtn.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      // 面板打开时检查是否有正在运行的复盘
      checkAndRestoreRunningReview();
    }
  });
  closeBtn.addEventListener('click', () => { panel.hidden = true; });

  // 页面加载时检查是否有正在运行的复盘
  checkAndRestoreRunningReview();

  loadHistoryReports();

  historySelect.addEventListener('change', async () => {
    if (!historySelect.value) return;
    try {
      const res = await fetch(`/api/review/report?date=${historySelect.value}`);
      if (res.ok) {
        const data = await res.json();
        resultEl.innerHTML = renderReviewReport(data);
      }
    } catch(e) {}
  });

  let pollTimer = null;

  // 检查并恢复正在运行的复盘状态
  async function checkAndRestoreRunningReview() {
    if (isRestoring) return;
    isRestoring = true;

    try {
      const res = await fetch(`/api/review/status?date=${encodeURIComponent(dateInput.value)}`);
      const status = await res.json();

      // 如果状态是运行中，恢复UI
      if (isRunningStatus(status.status)) {
        restoreProgressUI(status);
        // 启动轮询
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollStatus, 3000);
      }
    } catch (e) {
      console.warn('检查复盘运行状态失败:', e);
    } finally {
      isRestoring = false;
    }
  }

  // 判断状态是否为运行中
  function isRunningStatus(status) {
    const runningStatuses = ['loading', 'analyzing', 'sending', 'saving'];
    return runningStatuses.includes(status);
  }

  // 恢复进度UI
  function restoreProgressUI(status) {
    runBtn.disabled = true;
    runBtn.textContent = '⏳ 盘后复盘中...';
    progressCard.style.display = 'block';
    progressBar.style.width = (status.progress || 0) + '%';

    const statusMap = {
      loading: '正在加载数据...',
      analyzing: '盘后复盘中...',
      sending: '发送 Telegram...',
      saving: '保存报告...',
      done: '✅ 盘后复盘完成',
      error: '❌ 出错'
    };
    statusText.textContent = statusMap[status.status] || status.status || '处理中...';
    metaText.textContent = status.news_count ? `${status.news_count} 条新闻` : '';
    resultEl.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px;">盘后复盘中，请稍候...</div>';
  }

  runBtn.addEventListener('click', async () => {
    runBtn.disabled = true;
    runBtn.textContent = '⏳ 盘后复盘中...';
    progressCard.style.display = 'block';
    progressBar.style.width = '0%';
    statusText.textContent = '正在启动...';
    metaText.textContent = '';
    resultEl.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px;">盘后复盘中，请稍候...</div>';

    try {
      const startRes = await fetch('/api/review/run', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ date: dateInput.value || undefined }) });
      const startData = await startRes.json().catch(() => ({}));
      if (!startRes.ok) {
        throw new Error(startData.detail || startData.message || `HTTP ${startRes.status}`);
      }
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(pollStatus, 3000);
      pollStatus();
    } catch(e) {
      statusText.textContent = '启动失败：' + e.message;
      resultEl.innerHTML = `<div style="color:#ef4444;padding:12px;background:rgba(239,68,68,0.1);border-radius:6px;">❌ 盘后复盘启动失败<br><span style="font-size:13px;">${String(e.message || '未知错误')}</span></div>`;
      runBtn.disabled = false;
      runBtn.textContent = '▶ 运行盘后复盘';
    }
  });

  async function pollStatus() {
    try {
      const res = await fetch(`/api/review/status?date=${encodeURIComponent(dateInput.value)}`);
      const s = await res.json();
      const statusMap = { loading:'正在加载数据...', analyzing:'盘后复盘中...', sending:'发送 Telegram...', saving:'保存报告...', done:'✅ 盘后复盘完成', error:'❌ 出错' };
      statusText.textContent = statusMap[s.status] || s.status || '处理中...';
      progressBar.style.width = (s.progress || 0) + '%';
      metaText.textContent = s.news_count ? `${s.news_count} 条新闻` : '';
      if (s.status === 'done') {
        clearInterval(pollTimer);
        runBtn.disabled = false;
        runBtn.textContent = '▶ 运行盘后复盘';
        const rRes = await fetch(`/api/review/report?date=${encodeURIComponent(dateInput.value)}`);
        if (rRes.ok) {
          const data = await rRes.json();
          resultEl.innerHTML = renderReviewReport(data);
        }
      } else if (s.status === 'error') {
        clearInterval(pollTimer);
        runBtn.disabled = false;
        runBtn.textContent = '▶ 运行盘后复盘';
        resultEl.innerHTML = `<div style="color:#ef4444;padding:12px;background:rgba(239,68,68,0.1);border-radius:6px;">
          ❌ 盘后复盘失败<br>
          <span style="font-size:13px;">${s.current_step || '未知错误'}</span>
          ${s.suggestion ? `<br><span style="font-size:12px;color:var(--muted);">${s.suggestion}</span>` : ''}
        </div>`;
      }
    } catch(e) {
      clearInterval(pollTimer);
      runBtn.disabled = false;
      runBtn.textContent = '▶ 运行盘后复盘';
      resultEl.innerHTML = `<div style="color:#ef4444;padding:12px;background:rgba(239,68,68,0.1);border-radius:6px;">❌ 状态轮询失败<br><span style="font-size:13px;">${String(e.message || '网络异常')}</span></div>`;
    }
  }

  // 渲染盘后复盘报告
  function renderReviewReport(data) {
    if (!data || !data.date) {
      return '<div style="color:var(--muted); text-align:center; padding:20px;">暂无盘后复盘报告</div>';
    }
    
    // 适配后端数据结构：recommendation_snapshot + actual
    const snapshot = data.recommendation_snapshot || data.recommended_sector || {};
    const actual = data.actual || {};
    const stocks = actual.stocks || data.recommended_stocks || [];
    const topStock = stocks.length > 0 ? stocks[0] : null;
    const evaluation = data.evaluation || {};
    
    const colorPct = (pct) => {
      if (pct > 0) return '#22c55e';
      if (pct < 0) return '#ef4444';
      return 'var(--muted)';
    };
    const formatPct = (pct) => {
      if (pct === undefined || pct === null) return '-';
      const sign = pct > 0 ? '+' : '';
      return sign + Number(pct).toFixed(2) + '%';
    };
    
    let html = `
      <div style="padding:12px; background:var(--bg-card); border-radius:8px; margin-bottom:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <div style="font-size:16px; font-weight:600; color:var(--text);">
            📅 ${data.date} 盘后复盘
          </div>
          <span style="font-size:11px; color:var(--text-secondary); background:var(--bg-hover); padding:4px 10px; border-radius:12px;">推荐板块</span>
        </div>
        <div style="margin-bottom:8px;">
          <span style="font-size:18px; font-weight:700; color:var(--text);">${snapshot.sector_name || snapshot.name || '-'}</span>
          <span style="font-size:13px; color:var(--muted); margin-left:6px;">${snapshot.sector_code || snapshot.code || ''}</span>
        </div>
        <div style="font-size:22px; font-weight:700; color:${colorPct(snapshot.entry_change_pct || snapshot.change_pct)}; margin-bottom:8px;">
          ${formatPct(snapshot.entry_change_pct || snapshot.change_pct)}
        </div>
        <div style="font-size:13px; color:var(--text-secondary); line-height:1.6; margin-bottom:12px;">
          ${snapshot.logic || ''}
        </div>
        ${topStock ? `
        <div style="display:flex; align-items:center; gap:8px; font-size:13px; color:var(--text); margin-bottom:12px;">
          <span style="color:var(--muted);">🏆 领涨股</span>
          <span style="font-weight:600;">${topStock.name}</span>
          <span style="font-weight:600; color:${colorPct(topStock.change_pct)};">${formatPct(topStock.change_pct)}</span>
        </div>` : ''}
        ${evaluation.verdict ? `
        <div style="font-size:13px; color:var(--text); margin-top:12px; padding-top:12px; border-top:1px solid var(--border);">
          <span style="color:var(--muted);">复盘评价：</span>
          <span style="font-weight:600;">${evaluation.verdict}</span>
        </div>` : ''}
      </div>
    `;
    
    if (stocks.length > 0) {
      html += `
        <div style="padding:12px; background:var(--bg-card); border-radius:8px; margin-bottom:12px;">
          <div style="font-size:13px; font-weight:600; color:var(--text); margin-bottom:10px;">推荐成分股 TOP ${stocks.length}</div>
          <div style="display:flex; flex-wrap:wrap; gap:8px;">
            ${stocks.map(s => `
              <span style="background:rgba(41,98,255,0.1); border:1px solid rgba(41,98,255,0.2); padding:6px 12px; border-radius:6px; font-size:12px; color:var(--text); white-space:nowrap;">
                ${s.name} <span style="font-weight:600; color:${colorPct(s.change_pct)};">${formatPct(s.change_pct)}</span>
              </span>
            `).join('')}
          </div>
        </div>
      `;
    }
    
    if (data.llm_analysis) {
      html += renderStructuredAnalysis(data.llm_analysis);
    }
    
    return html;
  }

  // 结构化渲染 AI 分析内容
  function renderStructuredAnalysis(llmText) {
    if (!llmText || llmText.trim().length === 0) return '';
    
    const sections = parseLLMAnalysisSections(llmText);
    
    let html = '<div style="padding:12px; background:var(--bg-card); border-radius:8px; margin-bottom:12px;">';
    html += '<div style="font-size:13px; font-weight:600; color:var(--text); margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--border);">🤖 AI 盘后复盘</div>';
    
    // 宏观形势判断
    if (sections.macro) {
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">📊 宏观形势判断</div>
        <div style="font-size:13px; color:var(--text); line-height:1.6; background:var(--bg-hover); padding:10px 12px; border-radius:6px;">${escapeHtml(sections.macro)}</div>
      </div>`;
    }
    
    // 推荐板块
    if (sections.sector) {
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">🎯 推荐板块</div>
        <div style="font-size:13px; color:var(--text); line-height:1.6; background:var(--bg-hover); padding:10px 12px; border-radius:6px;">${escapeHtml(sections.sector)}</div>
      </div>`;
    }
    
    // 推荐理由
    if (sections.reason) {
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">💡 推荐理由</div>
        <div style="font-size:13px; color:var(--text); line-height:1.6; background:var(--bg-hover); padding:10px 12px; border-radius:6px;">${escapeHtml(sections.reason)}</div>
      </div>`;
    }
    
    // 关键催化
    if (sections.catalyst) {
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">⚡ 关键催化</div>
        <div style="font-size:13px; color:var(--text); line-height:1.6; background:var(--bg-hover); padding:10px 12px; border-radius:6px;">${escapeHtml(sections.catalyst)}</div>
      </div>`;
    }
    
    // 相关新闻
    if (sections.news && sections.news.length > 0) {
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">📰 相关新闻 (${sections.news.length} 条)</div>
        <div style="background:var(--bg-hover); border-radius:6px; padding:10px 12px;">`;
      sections.news.forEach(news => {
        html += `<div style="font-size:13px; color:var(--text); line-height:1.5; padding:6px 0; border-bottom:1px solid var(--border);">${escapeHtml(news)}</div>`;
      });
      html += '</div></div>';
    }
    
    // 风险提示
    if (sections.risk) {
      html += `<div style="margin-bottom:0;">
        <div style="font-size:12px; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">⚠️ 风险提示</div>
        <div style="font-size:13px; color:#f87171; line-height:1.6; background:rgba(239,68,68,0.08); border:1px solid rgba(239,68,68,0.2); padding:10px 12px; border-radius:6px;">${escapeHtml(sections.risk)}</div>
      </div>`;
    }
    
    // 如果没有解析出结构化内容，显示原始文本
    if (!sections.macro && !sections.sector && !sections.reason && !sections.catalyst && sections.news.length === 0 && !sections.risk) {
      html += `<div style="font-size:13px; color:var(--text); line-height:1.6; white-space:pre-wrap;">${escapeHtml(llmText)}</div>`;
    }
    
    html += '</div>';
    return html;
  }

  // 解析 LLM 分析文本为结构化段落
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
      const lines = newsText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
      sections.news = lines;
    }
    
    // 风险提示（支持中英文冒号）
    const riskMatch = text.match(/风险提示[:：]\s*([\s\S]*?)$/i);
    if (riskMatch) sections.risk = riskMatch[1].trim();
    
    return sections;
  }

  // HTML 转义
  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // 加载历史报告列表
  async function loadHistoryReports() {
    try {
      const res = await fetch('/api/review/history');
      if (res.ok) {
        const data = await res.json();
        if (data.dates && data.dates.length > 0) {
          historySelect.innerHTML = '<option value="">历史报告...</option>';
          data.dates.forEach(date => {
            const option = document.createElement('option');
            option.value = date;
            option.textContent = date;
            historySelect.appendChild(option);
          });
        }
      }
    } catch(e) {
      console.warn('加载历史报告失败:', e);
    }
  }
})();