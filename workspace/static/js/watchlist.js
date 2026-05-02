// watchlist.js - 侧边栏监控股票函数

async function buildWatchSidebar() {
  const watchListEl = document.getElementById('watchList');
  const symbolSelect = document.getElementById('symbolSelect');
  const watchlist = state.config.watchlist || [];
  watchListEl.innerHTML = '';
  for (const item of watchlist) {
    const div = document.createElement('div');
    div.className = 'watch-item';
    div.dataset.symbol = `${item.market}:${item.symbol}`;
    div.innerHTML = `<div style="font-weight:700">${item.symbol} ${item.name || ''}</div><div style="color:var(--muted); margin-top:6px" id="quote-${item.symbol}">加载中...</div>`;
    div.addEventListener('click', () => {
      markUserInteraction();
      symbolSelect.value = div.dataset.symbol;
      symbolSelect.dispatchEvent(new Event('change'));
      highlightActiveWatch();
    });
    watchListEl.appendChild(div);
    fetch(`/api/quote/${item.symbol}?market=${encodeURIComponent(item.market)}`).then(r=>r.ok? r.json():null).then(q=>{
      if (!q) return;
      state.watchQuotes[item.symbol] = q;
      const el = document.getElementById(`quote-${item.symbol}`);
      if (el) {
        if (q.error) {
          el.textContent = '⚠️ 数据暂不可用';
          el.style.color = '#ef4444';
        } else {
          el.textContent = `${formatNum(q.price)} ${q.change >=0? '▲':'▼'}${(q.change_pct||0).toFixed(2)}%`;
          el.style.color = q.change>0? 'var(--up)': q.change<0? 'var(--down)': 'var(--muted)';
        }
      }
    }).catch(()=>{});
  }
  highlightActiveWatch();
}

function highlightActiveWatch() {
  const watchListEl = document.getElementById('watchList');
  const symbolSelect = document.getElementById('symbolSelect');
  const items = watchListEl.querySelectorAll('.watch-item');
  items.forEach(it => it.classList.toggle('active', it.dataset.symbol === symbolSelect.value));
  
  // 同时更新悬浮面板的高亮状态
  updateSymbolPanelHighlight();
}

// 更新悬浮面板中的高亮状态
function updateSymbolPanelHighlight() {
  const symbolSelect = document.getElementById('symbolSelect');
  if (!symbolSelect) return;
  
  const currentVal = symbolSelect.value;
  const panelItems = document.querySelectorAll('.symbol-list-item');
  panelItems.forEach(item => {
    item.classList.toggle('active', item.dataset.value === currentVal);
  });
}

// 更新悬浮面板中的股票价格
function updateSymbolPanelPrices() {
  const container = document.getElementById('symbolListContainer');
  if (!container) return;
  
  const items = container.querySelectorAll('.symbol-list-item');
  items.forEach(item => {
    const symbol = item.querySelector('.symbol-code')?.textContent;
    if (!symbol) return;
    
    const quote = state.watchQuotes[symbol];
    const priceEl = item.querySelector('.symbol-price');
    const changeEl = item.querySelector('.symbol-change');
    
    if (quote && !quote.error && priceEl && changeEl) {
      const price = Number(quote.price || 0).toFixed(3);
      const changePct = Math.abs(quote.change_pct || 0).toFixed(2);
      const changeSymbol = quote.change >= 0 ? '↑' : '↓';
      
      priceEl.textContent = price;
      changeEl.textContent = `${changeSymbol}${changePct}%`;
      changeEl.className = `symbol-change ${quote.change >= 0 ? 'up' : 'down'}`;
    }
  });
}
