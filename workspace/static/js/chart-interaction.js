// chart-interaction.js - 交互逻辑函数

// 触摸设备检测
const isTouchDevice = window.matchMedia('(pointer: coarse)').matches;

function getCanvasPos(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  const touch = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
  return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
}

// 获取触摸/鼠标事件的坐标（支持多点触摸）
function getEventPos(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  
  // 优先使用触摸事件
  if (e.touches && e.touches.length > 0) {
    return { 
      x: e.touches[0].clientX - rect.left, 
      y: e.touches[0].clientY - rect.top,
      clientX: e.touches[0].clientX,
      clientY: e.touches[0].clientY
    };
  }
  
  // 触摸结束事件
  if (e.changedTouches && e.changedTouches.length > 0) {
    return { 
      x: e.changedTouches[0].clientX - rect.left, 
      y: e.changedTouches[0].clientY - rect.top,
      clientX: e.changedTouches[0].clientX,
      clientY: e.changedTouches[0].clientY
    };
  }
  
  // 鼠标事件
  return { 
    x: e.clientX - rect.left, 
    y: e.clientY - rect.top,
    clientX: e.clientX,
    clientY: e.clientY
  };
}

function getTouchDistance(event) {
  if (!event.touches || event.touches.length < 2) return 0;
  const [a, b] = event.touches;
  return Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
}

function getCanvasIndexFromEvent(event) {
  const layout = klineCanvas._layout;
  if (!layout || !state.current?.kline?.length) return -1;
  const { x } = getCanvasPos(klineCanvas, event);
  if (x < layout.left || x > layout.left + layout.plotWidth) return -1;
  const localIndex = Math.floor((x - layout.left) / layout.step);
  const globalIndex = layout.startIndex + localIndex;
  return Math.max(layout.startIndex, Math.min(layout.endIndex - 1, globalIndex));
}

function updateHoverFromEvent(event) {
  const pos = getEventPos(klineCanvas, event);
  const index = getCanvasIndexFromEvent(event);
  if (index < 0) {
    hideTooltip();
    return -1;
  }
  state.hoverIndex = index;
  scheduleRedraw();
  showTooltip(pos.clientX, pos.clientY, state.current.kline[index]);
  return index;
}

function onPointerMove(event) {
  updateHoverFromEvent(event);
}

function onKlineClick(event) {
  const index = getCanvasIndexFromEvent(event);
  if (index < 0) return;
  state.selectedIndex = index;
  updateDetailPanel(index);
  renderAll();
}

function onCanvasTouchStart(event) {
  if (!state.current?.kline?.length) return;
  
  // 在触摸设备上阻止默认行为以避免页面滚动
  if (isTouchDevice) {
    event.preventDefault();
  }
  
  markUserInteraction();

  if (event.touches.length === 2) {
    state.touch.mode = 'pinch';
    state.touch.startDistance = getTouchDistance(event);
    state.touch.startVisibleCount = state.visibleCount;
    state.touch.moved = false;
    // 双指操作时隐藏 tooltip
    hideTooltip();
    return;
  }

  if (event.touches.length === 1) {
    const pos = getCanvasPos(klineCanvas, event);
    state.touch.mode = 'pan';
    state.touch.startX = pos.x;
    state.touch.startY = pos.y; // 记录 Y 坐标用于判断滑动方向
    state.touch.startOffset = state.dataOffset;
    state.touch.moved = false;
    state.touch.startTime = Date.now();
    
    // 延迟显示 tooltip，避免快速滑动时闪烁
    state.touch.tooltipTimer = setTimeout(() => {
      if (!state.touch.moved && state.touch.mode === 'pan') {
        updateHoverFromEvent(event);
      }
    }, 100);
  }
}

function onCanvasTouchMove(event) {
  if (!state.current?.kline?.length || !state.touch.mode) return;
  
  // 在触摸设备上阻止默认行为
  if (isTouchDevice) {
    event.preventDefault();
  }
  
  markUserInteraction();

  if (state.touch.mode === 'pinch' && event.touches.length === 2) {
    const distance = getTouchDistance(event);
    if (!distance || !state.touch.startDistance) return;
    const maxVisible = getInteractionMaxVisibleCount();
    const scaledVisible = Math.round(state.touch.startVisibleCount * (state.touch.startDistance / distance));
    const nextVisible = clamp(scaledVisible, INTERACTION_LIMITS.minVisibleCount, maxVisible);
    if (nextVisible !== state.visibleCount) {
      state.visibleCount = nextVisible;
      clampViewportState();
      state.touch.moved = true;
      scheduleRedraw();
    }
    return;
  }

  if (state.touch.mode === 'pan' && event.touches.length === 1) {
    const pos = getCanvasPos(klineCanvas, event);
    const deltaX = pos.x - state.touch.startX;
    const deltaY = pos.y - state.touch.startY;
    
    // 判断滑动方向，如果垂直滑动占主导，不处理（让页面滚动）
    if (Math.abs(deltaY) > Math.abs(deltaX) * 1.5) {
      return;
    }
    
    // 如果移动距离超过阈值，标记为已移动
    if (Math.abs(deltaX) > 5) {
      state.touch.moved = true;
      // 取消 tooltip 显示
      if (state.touch.tooltipTimer) {
        clearTimeout(state.touch.tooltipTimer);
        state.touch.tooltipTimer = null;
      }
      hideTooltip();
    }
    
    const candleShift = Math.round(deltaX / INTERACTION_LIMITS.panStepPx);
    const maxOffset = Math.max(0, (state.current?.kline?.length || 0) - state.visibleCount);
    const nextOffset = clamp(state.touch.startOffset - candleShift, 0, maxOffset);
    if (nextOffset !== state.dataOffset) {
      state.dataOffset = nextOffset;
      scheduleRedraw();
    }
  }
}

function onCanvasTouchEnd(event) {
  // 清理 tooltip 定时器
  if (state.touch.tooltipTimer) {
    clearTimeout(state.touch.tooltipTimer);
    state.touch.tooltipTimer = null;
  }
  
  // 如果还有剩余触摸点，继续跟踪
  if (event.touches.length === 1) {
    const pos = getCanvasPos(klineCanvas, event);
    state.touch.mode = 'pan';
    state.touch.startX = pos.x;
    state.touch.startY = pos.y;
    state.touch.startOffset = state.dataOffset;
    state.touch.startDistance = 0;
    state.touch.startVisibleCount = state.visibleCount;
    state.touch.moved = false;
    return;
  }

  // 检查是否是点击（未移动且时间短）
  const touchDuration = Date.now() - (state.touch.startTime || 0);
  const wasClick = !state.touch.moved && touchDuration < 300;
  
  // 如果是点击，触发 K 线点击事件
  if (wasClick && event.changedTouches.length > 0) {
    onKlineClick(event);
  }

  state.touch.mode = null;
  state.touch.startDistance = 0;
  state.touch.moved = false;
  state.touch.startTime = 0;
  
  // 延迟隐藏 tooltip，让用户有时间查看
  if (!wasClick) {
    setTimeout(() => {
      hideTooltip();
    }, 500);
  }
}

function showTooltip(clientX, clientY, bar) {
  if (!tooltipEl) return;
  
  tooltipEl.style.display = 'block';
  
  // 智能定位：避免 tooltip 超出屏幕边界
  const tooltipWidth = tooltipEl.offsetWidth || 170;
  const tooltipHeight = tooltipEl.offsetHeight || 120;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  
  let left = clientX + 14;
  let top = clientY + 14;
  
  // 如果右侧超出屏幕，显示在左侧
  if (left + tooltipWidth > viewportWidth - 10) {
    left = clientX - tooltipWidth - 14;
  }
  
  // 如果底部超出屏幕，显示在上方
  if (top + tooltipHeight > viewportHeight - 10) {
    top = clientY - tooltipHeight - 14;
  }
  
  // 确保不超出左边界和上边界
  left = Math.max(10, left);
  top = Math.max(10, top);
  
  tooltipEl.style.left = left + 'px';
  tooltipEl.style.top = top + 'px';
  tooltipEl.innerHTML = [
    `<strong>${bar.time}</strong>`,
    `开：${formatNum(bar.open)}`,
    `高：${formatNum(bar.high)}`,
    `低：${formatNum(bar.low)}`,
    `收：${formatNum(bar.close)}`,
    `量：${Number(bar.volume || 0).toLocaleString('zh-CN')}`,
  ].join('<br/>');
}

function hideTooltip() {
  state.hoverIndex = -1;
  tooltipEl.style.display = 'none';
  renderAll();
}

function markUserInteraction() {
  userInteracted = true;
  if (userInteractionResetTimer) clearTimeout(userInteractionResetTimer);
  userInteractionResetTimer = setTimeout(() => {
    userInteracted = false;
  }, 3000);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function clampViewportState() {
  const total = state.current?.kline?.length || 0;
  if (!total) {
    state.visibleCount = INTERACTION_LIMITS.minVisibleCount;
    state.dataOffset = 0;
    return;
  }
  const maxVisible = getInteractionMaxVisibleCount();
  state.visibleCount = clamp(Math.round(state.visibleCount || maxVisible), INTERACTION_LIMITS.minVisibleCount, maxVisible);
  const maxOffset = Math.max(0, total - state.visibleCount);
  state.dataOffset = clamp(Math.round(state.dataOffset || 0), 0, maxOffset);
}

function clampInteractiveState() {
  const klineLength = state.current?.kline?.length || 0;
  const macdLength = state.current?.macd?.length || 0;
  const maxIndex = Math.max(0, Math.min(klineLength, macdLength || klineLength) - 1);

  clampViewportState();

  if (!klineLength) {
    state.hoverIndex = -1;
    state.selectedIndex = -1;
    return;
  }

  if (state.hoverIndex >= klineLength) {
    state.hoverIndex = maxIndex;
  }
  if (state.selectedIndex >= klineLength) {
    state.selectedIndex = maxIndex;
  }
}

function getInteractionMaxVisibleCount() {
  const total = state.current?.kline?.length || 0;
  return total ? Math.max(INTERACTION_LIMITS.minVisibleCount, Math.min(INTERACTION_LIMITS.maxVisibleCount, total)) : INTERACTION_LIMITS.maxVisibleCount;
}

function resetViewport() {
  const total = state.current?.kline?.length || 0;
  const maxVisible = total ? Math.max(INTERACTION_LIMITS.minVisibleCount, Math.min(INTERACTION_LIMITS.maxVisibleCount, total)) : 60;
  state.visibleCount = Math.min(60, maxVisible);
  state.dataOffset = 0;
}
