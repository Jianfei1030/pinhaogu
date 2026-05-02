// api.js - 数据获取函数

async function loadQuote(market, symbol) {
  const params = new URLSearchParams({ market });
  const res = await fetch(`/api/quote/${symbol}?${params.toString()}`);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

async function loadCalibrationStatus(date) {
  const params = new URLSearchParams({ date });
  const res = await fetch(`/api/calibration/status?${params.toString()}`);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

async function loadData(options = {}) {
  const { clearSelection = false } = options;
  const { market, symbol, period, date } = getSelections();
  if (!market || !symbol || !period || !date) return;
  if (clearSelection) {
    state.selectedIndex = -1;
    state.hoverIndex = -1;
    tooltipEl.style.display = 'none';
    clearDetailPanel();
  }
  setLoading(true);
  try {
    const params = new URLSearchParams({ market, symbol, period, date });
    const [res, quote, calibration] = await Promise.all([
      fetch(`/api/kline?${params.toString()}`),
      loadQuote(market, symbol).catch((err) => ({ symbol, market, error: err.message || '数据暂不可用' })),
      loadCalibrationStatus(date).catch(() => ({ date, done: false, source: 'THS-SIM' })),
    ]);
    if (!res.ok) throw new Error(await res.text());
    const nextData = await res.json();
    if (!hasRenderableData(nextData)) {
      throw new Error('返回数据不完整');
    }
    state.current = nextData;
    state.currentQuote = quote;
    state.calibration = calibration;
    resetViewport();
    clampInteractiveState();
    if (!state.current.kline?.length) {
      state.selectedIndex = -1;
      clearDetailPanel();
    } else if (!state.initialSelectionDone) {
      state.selectedIndex = state.current.kline.length - 1;
      state.initialSelectionDone = true;
      updateDetailPanel(state.selectedIndex);
    } else if (state.selectedIndex >= state.current.kline.length) {
      state.selectedIndex = state.current.kline.length - 1;
      updateDetailPanel(state.selectedIndex);
    } else if (state.selectedIndex >= 0) {
      updateDetailPanel(state.selectedIndex);
    }
    renderSummary();
    chartsEl.style.display = 'block';
    emptyEl.style.display = state.current.kline?.length ? 'none' : 'block';
    setLoading(false);
    requestAnimationFrame(() => renderAll());
  } catch (err) {
    console.error(err);
    setLoading(true, '加载失败：' + err.message);
  }
}

async function loadAlerts() {
  alertListEl.innerHTML = '<div class="loading">正在加载告警规则...</div>';
  try {
    const res = await fetch('/api/alerts');
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.alerts = (data.alerts || []).map((alert, index) => normalizeAlert(alert, index));
    state.alerts.forEach((alert, index) => {
      state.alertEnabledMap[getAlertKey(alert, index)] = !!alert.enabled;
    });
    saveAlertEnabledMap();
    renderAlertList();
  } catch (err) {
    console.error(err);
    alertListEl.innerHTML = `<div class="alert-empty">加载告警规则失败：${escapeHtml(err.message)}</div>`;
  }
}

// Note: News loading is now fully handled by news_v2.js
// This file no longer defines loadRecentNews

async function fetchMonitorStatus() {
  try {
    const res = await fetch('/api/monitor/status');
    if (!res.ok) throw new Error('status fetch failed');
    const data = await res.json();
    const ms = data.market_status || {};
    if (!data.market_open) {
      const nextOpen = ms.next_open ? `，下次开盘 ${ms.next_open}` : '';
      const markets = Object.entries(ms.markets || {}).map(([m, v]) => `${m} ${v.start}-${v.end}`).join(' / ');
      monitorStatusEl.innerHTML = `⚪ 已收盘${nextOpen} | ${markets}`;
      monitorStatusEl.style.opacity = '0.6';
    } else if (data.running) {
      monitorStatusEl.innerHTML = `🟢 监控运行中 | 上次更新：${data.last_tick || data.start_time || ''}`;
      monitorStatusEl.style.opacity = '1';
    } else {
      monitorStatusEl.innerHTML = `🔴 监控未运行`;
      monitorStatusEl.style.opacity = '1';
    }
  } catch (e) {
    monitorStatusEl.innerHTML = `🔴 监控状态未知`;
  }
}

async function loadHistoryReports() {
  try {
    const res = await fetch('/api/analysis/status');
    const status = await res.json();
    if (status.report_path) {
      const opt = document.createElement('option');
      opt.value = status.date || dateInput.value;
      opt.textContent = status.date || dateInput.value;
      historySelect.appendChild(opt);
    }
  } catch(e) {}
}

async function fetchNewsStatus() {
  try {
    const date = dateInput.value;
    const resp = await fetch(`/api/news/status?date=${encodeURIComponent(date)}`);
    if (!resp.ok) throw new Error('news status fetch failed');
    const data = await resp.json();
    if (data.collector_running) {
      newsStatusIcon.textContent = '🔄';
      newsStatusText.textContent = `正在收集新闻...已收集 ${data.news_count} 条`;
      newsStatusDiv.style.background = 'rgba(251,191,36,0.15)';
    } else if (data.has_news) {
      newsStatusIcon.textContent = '✅';
      newsStatusText.textContent = `已加载 ${data.news_count} 条新闻`;
      newsStatusDiv.style.background = 'rgba(34,197,94,0.12)';
    } else {
      newsStatusIcon.textContent = '❌';
      newsStatusText.textContent = '今日暂无新闻数据，请等待收集';
      newsStatusDiv.style.background = 'rgba(239,68,68,0.15)';
    }
  } catch (e) {
    newsStatusIcon.textContent = '⚠️';
    newsStatusText.textContent = '新闻状态查询失败';
    newsStatusDiv.style.background = 'rgba(239,68,68,0.15)';
  }
}

async function saveAlert() {
  try {
    const payload = collectAlertFormData();
    const index = state.editingAlertIndex;
    const existingEnabled = index == null ? true : !!state.alerts[index]?.enabled;
    payload.enabled = existingEnabled;
    const url = index == null ? '/api/alerts' : `/api/alerts/${index}`;
    const method = index == null ? 'POST' : 'PUT';
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    const storageIndex = index == null ? state.alerts.length : index;
    state.alertEnabledMap[getAlertKey(payload, storageIndex)] = !!payload.enabled;
    saveAlertEnabledMap();
    closeAlertModal();
    await loadAlerts();
  } catch (err) {
    alert(err.message || '保存失败');
  }
}

async function handleAlertListClick(event) {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const index = Number(button.dataset.index);
  const action = button.dataset.action;
  if (!Number.isInteger(index) || !state.alerts[index]) return;

  if (action === 'edit') {
    openAlertModal(index);
    return;
  }
  if (action === 'delete') {
    if (!confirm(`确认删除告警规则「${state.alerts[index].name || `规则 ${index + 1}`}」吗？`)) return;
    try {
      const res = await fetch(`/api/alerts/${index}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await res.text());
      delete state.alertTestResults[index];
      await loadAlerts();
    } catch (err) {
      alert(err.message || '删除失败');
    }
    return;
  }
  if (action === 'test') {
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = '测试中...';
    try {
      const currentSelections = getSelections();
      const alertRule = state.alerts[index];
      const res = await fetch('/api/alerts/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          period: alertRule.period,
          conditions: getTestPayloadConditions(alertRule.conditions),
          symbol: currentSelections.symbol,
          date: currentSelections.date,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      state.alertTestResults[index] = await res.json();
      renderAlertList();
    } catch (err) {
      alert(err.message || '测试失败');
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function handleAlertListChange(event) {
  const toggle = event.target.closest('.alert-enabled-toggle');
  if (!toggle) return;
  const index = Number(toggle.dataset.index);
  const alertRule = state.alerts[index];
  if (!alertRule) return;
  const enabled = !!toggle.checked;
  const payload = { ...alertRule, enabled };
  try {
    const res = await fetch(`/api/alerts/${index}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    state.alerts[index].enabled = enabled;
  } catch (err) {
    console.warn('后端未持久化 enabled，已回退 localStorage', err);
    state.alerts[index].enabled = enabled;
  }
  state.alertEnabledMap[getAlertKey(state.alerts[index], index)] = enabled;
  saveAlertEnabledMap();
  renderAlertList();
}
