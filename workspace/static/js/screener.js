// screener.js - 选股面板函数

// 格式化成交额
function formatAmount(val) {
  if (val == null) return '-';
  if (val >= 1e8) return (val / 1e8).toFixed(2) + '亿';
  if (val >= 1e4) return (val / 1e4).toFixed(2) + '万';
  return val.toFixed(0);
}

// 加载盘前推荐数据
function loadPremarketRecommendation() {
  fetch('/api/premarket/latest').then(r => r.json()).then(data => {
    if (!data || !data.date) return; // 无数据，隐藏区域
    const section = document.getElementById('screenerPremarketSection');
    const dateEl = document.getElementById('screenerPremarketDate');
    const sectorEl = document.getElementById('screenerSectorInfo');
    const stocksEl = document.getElementById('screenerStocksList');

    // 显示区域
    section.style.display = 'block';

    // 日期
    dateEl.textContent = '分析日期: ' + data.date;

    // 板块信息
    const sector = data.recommended_sector;
    if (sector) {
      const pct = sector.change_pct;
      const color = pct >= 0 ? '#e91e63' : '#26a69a';
      const sign = pct >= 0 ? '+' : '';
      sectorEl.innerHTML =
        '<div style="margin-bottom:8px; font-size:14px;">'
        + '<span style="font-weight:600;">' + (sector.name || '-') + '</span>'
        + '<span style="margin-left:8px; color:' + color + '; font-weight:600;">' + sign + pct.toFixed(2) + '%</span>'
        + '</div>'
        + '<div style="font-size:12px; color:var(--muted,#9aa5ce); line-height:1.6;">推荐理由: ' + (sector.logic || '-') + '</div>';
    }

    // 成分股列表
    const stocks = data.recommended_stocks || [];
    // 按涨跌幅降序排列
    stocks.sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0));

    let html = '<table style="width:100%; border-collapse:collapse; font-size:13px; margin-top:12px;">'
      + '<thead><tr style="border-bottom:1px solid var(--border,#1f2937); color:var(--muted,#9aa5ce);">'
      + '<th style="text-align:left; padding:8px 6px;">代码</th>'
      + '<th style="text-align:left; padding:8px 6px;">名称</th>'
      + '<th style="text-align:right; padding:8px 6px;">最新价</th>'
      + '<th style="text-align:right; padding:8px 6px;">涨跌幅</th>'
      + '<th style="text-align:right; padding:8px 6px;">成交额</th>'
      + '</tr></thead><tbody>';

    stocks.forEach(s => {
      const pct = s.change_pct;
      const color = pct >= 0 ? '#e91e63' : '#26a69a';
      const sign = pct >= 0 ? '+' : '';
      html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">'
        + '<td style="padding:6px;">' + (s.code || '-') + '</td>'
        + '<td style="padding:6px;">' + (s.name || '-') + '</td>'
        + '<td style="padding:6px; text-align:right;">' + (s.price != null ? s.price.toFixed(2) : '-') + '</td>'
        + '<td style="padding:6px; text-align:right; color:' + color + '; font-weight:600;">'
        + (pct != null ? sign + pct.toFixed(2) + '%' : '-') + '</td>'
        + '<td style="padding:6px; text-align:right;">' + formatAmount(s.amount) + '</td>'
        + '</tr>';
    });

    html += '</tbody></table>';
    stocksEl.innerHTML = html;
  }).catch(err => {
    console.warn('加载盘前推荐失败', err);
  });
}

// 初始化：加载板块列表 + 盘前推荐（DOM 加载完成后）
function initScreener() {
  // 加载板块列表
  fetch('/api/screener/sectors').then(r=>r.json()).then(data=>{
    const sel = document.getElementById('sectorSelect');
    if (!sel) return;
    (data.sectors||[]).forEach(s=>{
      const opt = document.createElement('option');
      opt.value = s.code;
      opt.textContent = s.name + ' (' + s.count + '只)';
      sel.appendChild(opt);
    });
  }).catch(err => {
    console.warn('加载板块列表失败', err);
  });

  // 加载盘前推荐
  loadPremarketRecommendation();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initScreener);
} else {
  initScreener();
}

// 添加条件行
function updateScreenerConditionRow(row) {
  const type = row.querySelector('.condType').value;
  const rangeWrap = row.querySelector('.cond-range');
  const minInput = row.querySelector('.condMin');
  const maxInput = row.querySelector('.condMax');
  const noteEl = row.querySelector('.cond-note');
  const isCrossUp = type === 'macd_cross_up';
  rangeWrap.classList.toggle('hidden', isCrossUp);
  minInput.disabled = isCrossUp;
  maxInput.disabled = isCrossUp;
  if (isCrossUp) {
    minInput.value = '';
    maxInput.value = '';
    noteEl.textContent = '满足即通过';
  } else if (type.startsWith('macd_')) {
    noteEl.textContent = '默认 > 0';
  } else {
    noteEl.textContent = '';
  }
}

document.getElementById('screenerAddConditionBtn').onclick = function(){
  const div = document.createElement('div');
  div.className = 'screener-condition-row';
  div.innerHTML = '<select class="condType screener-cond-select">'
    + '<option value="change_pct">涨跌幅 (%)</option>'
    + '<option value="volume">成交量</option>'
    + '<option value="turnover">换手率 (%)</option>'
    + '<option value="pe_ratio">PE</option>'
    + '<option value="pb_ratio">PB</option>'
    + '<option value="macd_dif_slope">MACD DIF 斜率</option>'
    + '<option value="macd_dea_slope">MACD DEA 斜率</option>'
    + '<option value="macd_hist_slope">MACD 柱斜率</option>'
    + '<option value="macd_cross_up">MACD 金叉</option>'
    + '</select>'
    + '<span class="cond-range screener-cond-range">'
    + '<input type="number" class="condMin screener-cond-input" placeholder="最小值">'
    + '<span class="screener-cond-sep">~</span>'
    + '<input type="number" class="condMax screener-cond-input" placeholder="最大值">'
    + '</span>'
    + '<span class="cond-note screener-cond-note"></span>'
    + '<button class="removeCond screener-cond-remove" title="删除条件">✕</button>';
  div.querySelector('.removeCond').onclick = ()=>div.remove();
  div.querySelector('.condType').addEventListener('change', ()=>updateScreenerConditionRow(div));
  updateScreenerConditionRow(div);
  document.getElementById('screenerConditions').appendChild(div);
};

// 收起/展开
const screenerToggleEl = document.getElementById('screenerToggle');
if (screenerToggleEl) {
  screenerToggleEl.onclick = function(){
    const body = document.getElementById('screenerBody');
    body.style.display = body.style.display === 'none' ? 'block' : 'none';
    this.textContent = body.style.display === 'none' ? '展开' : '收起';
  };
}

// 选股按钮
document.getElementById('runScreenBtn').onclick = function(){
  const conditions = [];
  const sector = document.getElementById('sectorSelect').value;
  if(sector) conditions.push({type:'sector', sector_code:sector});

  document.querySelectorAll('#screenerConditions > div').forEach(row=>{
    const type = row.querySelector('.condType').value;
    const min = row.querySelector('.condMin').value;
    const max = row.querySelector('.condMax').value;
    const cond = {type};
    if(type !== 'macd_cross_up') {
      if(min) cond.min = parseFloat(min);
      if(max) cond.max = parseFloat(max);
    }
    conditions.push(cond);
  });

  const tbody = document.getElementById('screenerResultBody');
  tbody.innerHTML = '<tr><td colspan="4" class="screener-loading-cell">搜索中...</td></tr>';

  fetch('/api/screener/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({conditions})
  }).then(r=>r.json()).then(data=>{
    tbody.innerHTML = '';
    (data.results||[]).forEach(stock=>{
      const tr = document.createElement('tr');
      const changeColor = stock.change_pct > 0 ? 'up' : (stock.change_pct < 0 ? 'down' : 'flat');
      tr.innerHTML = '<td>' + stock.code + '</td>'
        + '<td>' + (stock.name||'') + '</td>'
        + '<td class="numeric">' + (stock.price||'-') + '</td>'
        + '<td class="numeric ' + changeColor + '">'
        + (stock.change_pct!=null ? (stock.change_pct>0?'+':'') + stock.change_pct.toFixed(2)+'%' : '-') + '</td>';
      tr.onclick = function(){
        const mkt = stock.code.startsWith('6') || stock.code.startsWith('9') ? 'A' : 'A';
        if(typeof selectStock === 'function') selectStock(mkt, stock.code);
        else {
          const symbolSelect = document.getElementById('symbolSelect');
          if (symbolSelect) {
            symbolSelect.value = 'A:' + stock.code;
            symbolSelect.dispatchEvent(new Event('change'));
          }
        }
      };
      tbody.appendChild(tr);
    });
    if(!data.results || data.results.length===0){
      tbody.innerHTML = '<tr><td colspan="4" class="screener-empty-cell">无匹配结果</td></tr>';
    }
  }).catch(err=>{
    tbody.innerHTML = '<tr><td colspan="4" class="screener-error-cell">查询失败：'+err.message+'</td></tr>';
  });
};

function selectStock(market, symbol) {
  const symbolSelect = document.getElementById('symbolSelect');
  if (symbolSelect) {
    symbolSelect.value = market + ':' + symbol;
    symbolSelect.dispatchEvent(new Event('change'));
  }
}
