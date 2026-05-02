// alerts.js - 告警面板函数

function loadAlertEnabledMap() {
  try {
    return JSON.parse(localStorage.getItem(ALERT_ENABLED_STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

// 立即初始化 state.alertEnabledMap
if (state && state.alertEnabledMap === undefined) {
  state.alertEnabledMap = loadAlertEnabledMap();
} else if (state) {
  state.alertEnabledMap = loadAlertEnabledMap();
}

function saveAlertEnabledMap() {
  localStorage.setItem(ALERT_ENABLED_STORAGE_KEY, JSON.stringify(state.alertEnabledMap || {}));
}

function getAlertKey(alert, index) {
  return `${alert?.name || 'alert'}__${alert?.period || 'period'}__${index}`;
}

function normalizeConditionTree(node) {
  if (Array.isArray(node)) {
    return {
      logic: 'AND',
      rules: node.map((item) => normalizeConditionTree(item)).filter(Boolean),
    };
  }
  if (!node || typeof node !== 'object') return null;
  if (node.indicator) {
    return {
      indicator: TEST_TO_API_INDICATOR[node.indicator] || node.indicator || 'macd_slope',
      op: node.op || '>',
      value: Number(node.value || 0),
    };
  }
  return {
    logic: String(node.logic || 'AND').toUpperCase(),
    rules: Array.isArray(node.rules) ? node.rules.map((item) => normalizeConditionTree(item)).filter(Boolean) : [],
  };
}

function normalizeAlert(alert, index) {
  const key = getAlertKey(alert, index);
  const enabled = typeof alert?.enabled === 'boolean'
    ? alert.enabled
    : state.alertEnabledMap[key] !== undefined
      ? !!state.alertEnabledMap[key]
      : true;
  return {
    name: alert?.name || '',
    period: alert?.period || '15min',
    conditions: normalizeConditionTree(alert?.conditions) || { logic: 'AND', rules: [] },
    cooldown: Number(alert?.cooldown || 0),
    enabled,
  };
}

function formatCondition(cond) {
  const label = INDICATOR_LABELS[cond?.indicator] || cond?.indicator || '未知指标';
  return `${label}${cond?.op || '>'}${Number(cond?.value ?? 0)}`;
}

function formatConditionsText(node) {
  if (!node) return '未配置条件';
  if (node.indicator) return formatCondition(node);
  const logic = String(node.logic || 'AND').toUpperCase();
  const rules = Array.isArray(node.rules) ? node.rules : [];
  if (!rules.length) return '未配置条件';
  return rules.map((item) => item?.indicator ? formatCondition(item) : `(${formatConditionsText(item)})`).join(` ${logic} `);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function getTestPayloadConditions(node) {
  if (Array.isArray(node)) {
    return node.map((item) => getTestPayloadConditions(item));
  }
  if (!node || typeof node !== 'object') {
    return { logic: 'AND', rules: [] };
  }
  if (node.indicator) {
    return {
      indicator: API_TO_TEST_INDICATOR[node.indicator] || node.indicator,
      op: node.op,
      value: Number(node.value),
    };
  }
  return {
    logic: String(node.logic || 'AND').toUpperCase(),
    rules: Array.isArray(node.rules) ? node.rules.map((item) => getTestPayloadConditions(item)) : [],
  };
}

function slopeArrow(value) {
  const num = Number(value || 0);
  if (num > 0.001) return { arrow: '↑', className: 'slope-up' };
  if (num < -0.001) return { arrow: '↓', className: 'slope-down' };
  return { arrow: '→', className: 'slope-flat' };
}

function renderAlertList() {
  if (!state.alerts.length) {
    alertListEl.innerHTML = '<div class="alert-empty">暂未配置告警规则，点击右上角"新增规则"开始。</div>';
    return;
  }

  alertListEl.innerHTML = state.alerts.map((alert, index) => {
    const result = state.alertTestResults[index];
    const conditionsText = formatConditionsText(alert.conditions);
    const triggerTimes = Array.isArray(result?.triggered_bars)
      ? result.triggered_bars.map((item) => item?.time || item?.ts || item).filter(Boolean).join(', ')
      : '';
    return `
      <div class="alert-item">
        <div class="alert-item-header">
          <div class="alert-item-main">
            <label class="switch" title="启用/禁用">
              <input type="checkbox" class="alert-enabled-toggle" data-index="${index}" ${alert.enabled ? 'checked' : ''} />
              <span class="slider"></span>
            </label>
            <div>
              <div class="alert-item-name">${escapeHtml(alert.name || `规则 ${index + 1}`)}</div>
              <div class="alert-item-meta">周期：${escapeHtml(alert.period)} | 条件：${escapeHtml(conditionsText)} | 冷却：${Number(alert.cooldown || 0)}s</div>
            </div>
          </div>
          <div class="alert-actions">
            <button type="button" data-action="test" data-index="${index}">测试</button>
            <button type="button" data-action="edit" data-index="${index}">编辑</button>
            <button type="button" data-action="delete" data-index="${index}">删除</button>
          </div>
        </div>
        ${result ? `<div class="alert-test-result">测试结果：${Number(result.total_bars_tested || 0)}根 bar 中，${Number(result.edge_triggered_count || 0)}次边缘触发${triggerTimes ? `<br/>触发时间：${escapeHtml(triggerTimes)}` : ''}</div>` : ''}
      </div>
    `;
  }).join('');
}

function defaultAlertRule() {
  return {
    name: '',
    period: '15min',
    conditions: {
      logic: 'AND',
      rules: [{ indicator: 'macd_slope', op: '>', value: 0 }],
    },
    cooldown: 300,
    enabled: true,
  };
}

function openAlertModal(index = null) {
  state.editingAlertIndex = index;
  const alert = index == null ? defaultAlertRule() : normalizeAlert(state.alerts[index], index);
  const topLevelConditions = alert.conditions?.indicator
    ? { logic: 'AND', rules: [alert.conditions] }
    : (alert.conditions || defaultAlertRule().conditions);
  const flatRules = Array.isArray(topLevelConditions.rules)
    ? topLevelConditions.rules.filter((rule) => rule && rule.indicator)
    : [];
  modalTitleEl.textContent = index == null ? '新增告警规则' : '编辑告警规则';
  alertNameEl.value = alert.name || '';
  alertPeriodEl.value = alert.period || '15min';
  alertLogicEl.value = topLevelConditions.logic || 'AND';
  alertCooldownEl.value = Number(alert.cooldown || 300);
  alertConditionsEl.innerHTML = '';
  (flatRules.length ? flatRules : defaultAlertRule().conditions.rules).forEach((cond) => addConditionRow(cond));
  alertModalEl.style.display = 'flex';
  setTimeout(() => alertNameEl.focus(), 0);
}

function closeAlertModal() {
  alertModalEl.style.display = 'none';
  state.editingAlertIndex = null;
}

function addConditionRow(condition = { indicator: 'macd_slope', op: '>', value: 0 }) {
  const row = document.createElement('div');
  row.className = 'condition-row';
  row.innerHTML = `
    <select class="cond-indicator">
      <option value="macd_slope">DIF 斜率</option>
      <option value="dea_slope">DEA 斜率</option>
      <option value="hist_slope">柱斜率</option>
      <option value="macd">DIF 值</option>
      <option value="macd_dea">DEA 值</option>
      <option value="macd_hist">柱值</option>
    </select>
    <select class="cond-op">
      <option value=">">&gt;</option>
      <option value="<">&lt;</option>
      <option value=">=">&gt;=</option>
      <option value="<=">&lt;=</option>
      <option value="==">==</option>
    </select>
    <input class="cond-value" type="number" step="0.01" value="0" />
    <button class="btn-remove-condition" type="button" title="删除">×</button>
  `;
  row.querySelector('.cond-indicator').value = condition.indicator || 'macd_slope';
  row.querySelector('.cond-op').value = condition.op || '>';
  row.querySelector('.cond-value').value = Number(condition.value || 0);
  row.querySelector('.btn-remove-condition').addEventListener('click', () => {
    if (alertConditionsEl.children.length <= 1) {
      alert('至少保留 1 个条件');
      return;
    }
    row.remove();
  });
  alertConditionsEl.appendChild(row);
}

function collectAlertFormData() {
  const name = alertNameEl.value.trim();
  const period = alertPeriodEl.value;
  const cooldown = Math.max(0, Number(alertCooldownEl.value || 0));
  const logic = String(alertLogicEl.value || 'AND').toUpperCase();
  const rules = Array.from(alertConditionsEl.querySelectorAll('.condition-row')).map((row) => ({
    indicator: row.querySelector('.cond-indicator').value,
    op: row.querySelector('.cond-op').value,
    value: Number(row.querySelector('.cond-value').value || 0),
  }));

  if (!name) throw new Error('请输入规则名称');
  if (!rules.length) throw new Error('至少添加 1 个条件');

  return {
    name,
    period,
    conditions: { logic, rules },
    cooldown,
    enabled: true,
  };
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  const intervalSec = parseInt(refreshSelect.value) || 60;
  const intervalMs = intervalSec * 1000;
  refreshTimer = setInterval(async () => {
    if (userInteracted) return;
    refreshHintEl.textContent = '🔄 刷新中';
    try {
      await loadData({ clearSelection: false });
    } finally {
      setTimeout(() => { refreshHintEl.textContent = ''; }, 800);
    }
  }, intervalMs);
}

function bindEvents() {
  symbolSelect.addEventListener('change', () => { markUserInteraction(); loadData({ clearSelection: true }); highlightActiveWatch(); });
  dateInput.addEventListener('change', () => { markUserInteraction(); loadData({ clearSelection: true }); });
  periodSelect.addEventListener('change', () => { markUserInteraction(); loadData({ clearSelection: true }); });
  refreshSelect.addEventListener('change', () => { startAutoRefresh(); });
  window.addEventListener('resize', () => state.current && renderAll());
  klineCanvas.addEventListener('mousemove', onPointerMove);
  klineCanvas.addEventListener('mouseleave', hideTooltip);
  klineCanvas.addEventListener('click', onKlineClick);
  klineCanvas.addEventListener('touchstart', onCanvasTouchStart, { passive: false });
  klineCanvas.addEventListener('touchmove', onCanvasTouchMove, { passive: false });
  klineCanvas.addEventListener('touchend', onCanvasTouchEnd, { passive: false });
  klineCanvas.addEventListener('touchcancel', onCanvasTouchEnd, { passive: false });

  addAlertBtn.addEventListener('click', () => openAlertModal());
  modalCloseEl.addEventListener('click', closeAlertModal);
  alertCancelBtn.addEventListener('click', closeAlertModal);
  addConditionBtn.addEventListener('click', () => addConditionRow());
  alertSaveBtn.addEventListener('click', saveAlert);
  alertModalEl.addEventListener('click', (event) => {
    if (event.target === alertModalEl) closeAlertModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && alertModalEl.style.display !== 'none') closeAlertModal();
  });
  alertListEl.addEventListener('click', handleAlertListClick);
  alertListEl.addEventListener('change', handleAlertListChange);
}
