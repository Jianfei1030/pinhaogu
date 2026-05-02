// chart-render.js - Canvas 绘制函数

function renderAll() {
  if (!hasRenderableData(state.current)) return;
  clampInteractiveState();
  const klineReady = renderKline();
  const macdReady = renderMacd();
  if (!klineReady || !macdReady) {
    requestRenderRetry();
  }
}

function calcSharedLayout(width, height, count) {
  const left = 56;
  const right = 16;
  const top = 12;
  const bottom = 28;
  const plotWidth = Math.max(10, width - left - right);
  const plotHeight = Math.max(10, height - top - bottom);
  const step = count > 0 ? plotWidth / count : plotWidth;
  return { left, right, top, bottom, plotWidth, plotHeight, step, width, height };
}

function niceTicks(min, max, count = 5) {
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  const raw = span / Math.max(1, count - 1);
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const residual = raw / magnitude;
  let nice = magnitude;
  if (residual >= 5) nice = 5 * magnitude;
  else if (residual >= 2) nice = 2 * magnitude;
  const niceMin = Math.floor(min / nice) * nice;
  const niceMax = Math.ceil(max / nice) * nice;
  const ticks = [];
  for (let v = niceMin; v <= niceMax + nice * 0.5; v += nice) ticks.push(v);
  return ticks;
}

function drawAxes(ctx, layout, yTicks, yToPixel, labels) {
  ctx.save();
  ctx.strokeStyle = COLORS.grid;
  ctx.fillStyle = COLORS.text;
  ctx.lineWidth = 1;
  ctx.font = '12px Segoe UI';

  yTicks.forEach((tick) => {
    const y = yToPixel(tick);
    ctx.beginPath();
    ctx.moveTo(layout.left, y);
    ctx.lineTo(layout.left + layout.plotWidth, y);
    ctx.stroke();
    ctx.fillText(tick.toFixed(3), 6, y + 4);
  });

  const labelCount = Math.min(labels.length, 6);
  for (let i = 0; i < labelCount; i++) {
    const index = Math.round((labels.length - 1) * (i / Math.max(1, labelCount - 1)));
    const x = layout.left + layout.step * index + layout.step / 2;
    const text = labels[index] || '';
    ctx.beginPath();
    ctx.moveTo(x, layout.top);
    ctx.lineTo(x, layout.top + layout.plotHeight);
    ctx.strokeStyle = 'rgba(45,45,68,0.5)';
    ctx.stroke();
    ctx.fillStyle = COLORS.muted || COLORS.text;
    ctx.fillText(text, x - 15, layout.top + layout.plotHeight + 18);
  }

  ctx.restore();
}

function renderKline() {
  const data = state.current;
  if (!data) return false;
  const view = getVisibleData();
  const list = view.kline || [];
  const { ctx, width, height, valid } = resizeCanvas(klineCanvas);
  if (!valid || !ctx) return false;
  ctx.clearRect(0, 0, width, height);
  if (!list.length) return true;

  const layout = calcSharedLayout(width, height, list.length);
  const lows = list.map(d => Number(d.low));
  const highs = list.map(d => Number(d.high));
  let min = Math.min(...lows);
  let max = Math.max(...highs);
  const pad = Math.max((max - min) * 0.08, max * 0.002);
  min -= pad;
  max += pad;
  const yTicks = niceTicks(min, max, 5);
  const yMin = yTicks[0];
  const yMax = yTicks[yTicks.length - 1];
  const yToPixel = (price) => layout.top + (yMax - price) / (yMax - yMin) * layout.plotHeight;

  drawAxes(ctx, layout, yTicks, yToPixel, list.map(d => d.time));

  const candleWidth = Math.max(3, Math.min(16, layout.step * 0.64));
  list.forEach((bar, index) => {
    const globalIndex = view.start + index;
    const x = layout.left + layout.step * index + layout.step / 2;
    const openY = yToPixel(Number(bar.open));
    const closeY = yToPixel(Number(bar.close));
    const highY = yToPixel(Number(bar.high));
    const lowY = yToPixel(Number(bar.low));
    const color = Number(bar.close) >= Number(bar.open) ? COLORS.up : COLORS.down;
    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(1, Math.abs(closeY - openY));

    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, highY);
    ctx.lineTo(x, lowY);
    ctx.stroke();
    ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);

    if (state.selectedIndex === globalIndex) {
      ctx.save();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x - candleWidth / 2 - 1, bodyTop - 1, candleWidth + 2, bodyHeight + 2);
      ctx.restore();
    }
  });

  const fullList = data.kline || [];
  const ma5 = computeMA(fullList, 5).slice(view.start, view.end);
  const ma10 = computeMA(fullList, 10).slice(view.start, view.end);
  const ma20 = computeMA(fullList, 20).slice(view.start, view.end);
  const ma60 = computeMA(fullList, 60).slice(view.start, view.end);

  drawMALine(ctx, layout, yToPixel, ma5, MA_COLORS.ma5);
  drawMALine(ctx, layout, yToPixel, ma10, MA_COLORS.ma10);
  drawMALine(ctx, layout, yToPixel, ma20, MA_COLORS.ma20);
  drawMALine(ctx, layout, yToPixel, ma60, MA_COLORS.ma60);

  if (state.hoverIndex >= view.start && state.hoverIndex < view.end) {
    const localHoverIndex = state.hoverIndex - view.start;
    const x = layout.left + layout.step * localHoverIndex + layout.step / 2;
    const bar = list[localHoverIndex];
    const y = yToPixel(Number(bar.close));
    drawCrosshair(ctx, layout, x, y);
  }

  klineCanvas._layout = { ...layout, startIndex: view.start, endIndex: view.end };
  return true;
}

function drawMALine(ctx, layout, yToPixel, arr, color) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < arr.length; i++) {
    if (arr[i] == null) continue;
    const x = layout.left + layout.step * i + layout.step / 2;
    const y = yToPixel(arr[i]);
    if (!started) { ctx.moveTo(x, y); started = true; }
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.restore();
}

function renderMacd() {
  const data = state.current;
  if (!data) return false;
  const view = getVisibleData();
  const kline = view.kline || [];
  const list = view.macd || [];
  const { ctx, width, height, valid } = resizeCanvas(macdCanvas);
  if (!valid || !ctx) return false;
  ctx.clearRect(0, 0, width, height);
  if (!list.length) return true;

  const layout = calcSharedLayout(width, height, kline.length || list.length);
  const values = [];
  list.forEach(d => values.push(Number(d.macd || 0), Number(d.dea || 0), Number(d.hist || 0)));
  let min = Math.min(...values, 0);
  let max = Math.max(...values, 0);
  const pad = Math.max((max - min) * 0.12, 0.02);
  min -= pad;
  max += pad;
  const ticks = niceTicks(min, max, 5);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const yToPixel = (val) => layout.top + (yMax - val) / (yMax - yMin) * layout.plotHeight;

  drawAxes(ctx, layout, ticks, yToPixel, (kline.length ? kline : list).map(d => d.time));

  const zeroY = yToPixel(0);
  ctx.save();
  ctx.strokeStyle = COLORS.cross;
  ctx.beginPath();
  ctx.moveTo(layout.left, zeroY);
  ctx.lineTo(layout.left + layout.plotWidth, zeroY);
  ctx.stroke();
  ctx.restore();

  const barWidth = Math.max(2, Math.min(12, layout.step * 0.58));
  list.forEach((bar, index) => {
    const x = layout.left + layout.step * index + layout.step / 2;
    const hist = Number(bar.hist || 0);
    const y = yToPixel(hist);
    ctx.fillStyle = hist >= 0 ? COLORS.hist_up : COLORS.hist_down;
    ctx.fillRect(x - barWidth / 2, Math.min(zeroY, y), barWidth, Math.max(1, Math.abs(y - zeroY)));
  });

  drawLine(ctx, list, layout, yToPixel, 'macd', COLORS.dif);
  drawLine(ctx, list, layout, yToPixel, 'dea', COLORS.dea);

  if (state.selectedIndex >= view.start && state.selectedIndex < view.end) {
    const localSelectedIndex = state.selectedIndex - view.start;
    const selectedX = layout.left + layout.step * localSelectedIndex + layout.step / 2;
    ctx.save();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(selectedX, layout.top);
    ctx.lineTo(selectedX, layout.top + layout.plotHeight);
    ctx.stroke();
    ctx.restore();
  }
  return true;
}

function drawLine(ctx, list, layout, yToPixel, key, color) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  list.forEach((row, index) => {
    const x = layout.left + layout.step * index + layout.step / 2;
    const y = yToPixel(Number(row[key] || 0));
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
}

function drawCrosshair(ctx, layout, x, y) {
  ctx.save();
  ctx.strokeStyle = COLORS.cross;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, layout.top);
  ctx.lineTo(x, layout.top + layout.plotHeight);
  ctx.moveTo(layout.left, y);
  ctx.lineTo(layout.left + layout.plotWidth, y);
  ctx.stroke();
  ctx.restore();
}

function resizeCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.floor(rect.width || 0);
  const height = Math.floor(rect.height || 0);
  const ctx = canvas.getContext('2d');
  if (!ctx || width <= 0 || height <= 0) {
    return { ctx, width, height, valid: false };
  }
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height, valid: true };
}

function hasRenderableData(data) {
  return !!(data && typeof data === 'object' && Array.isArray(data.kline) && Array.isArray(data.macd));
}

function setLoading(flag, text = '正在加载数据...') {
  loadingEl.style.display = flag ? 'block' : 'none';
  loadingEl.textContent = text;
  if (flag) {
    chartsEl.style.display = 'none';
    emptyEl.style.display = 'none';
  }
}

function getVisibleRange() {
  const total = state.current?.kline?.length || 0;
  clampViewportState();
  const visibleCount = Math.min(state.visibleCount, total || state.visibleCount);
  const end = total - state.dataOffset;
  const start = Math.max(0, end - visibleCount);
  return { start, end, visibleCount: Math.max(0, end - start), total };
}

function getVisibleData() {
  const { start, end } = getVisibleRange();
  return {
    start,
    end,
    kline: (state.current?.kline || []).slice(start, end),
    macd: (state.current?.macd || []).slice(start, end),
  };
}

function scheduleRedraw() {
  if (rafId) return;
  rafId = requestAnimationFrame(() => {
    renderAll();
    rafId = null;
  });
}

function requestRenderRetry() {
  if (requestRenderRetry._pending) return;
  requestRenderRetry._pending = true;
  requestAnimationFrame(() => {
    requestRenderRetry._pending = false;
    if (hasRenderableData(state.current)) {
      renderAll();
    }
  });
}
