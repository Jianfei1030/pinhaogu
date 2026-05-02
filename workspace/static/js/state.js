// state.js - 全局状态定义
const COLORS = {
  up: '#e74c3c',
  down: '#2ecc71',
  bg: '#1a1a2e',
  grid: '#2d2d44',
  text: '#e0e0e0',
  dif: '#ffffff',
  dea: '#f1c40f',
  hist_up: '#e74c3c',
  hist_down: '#2ecc71',
  cross: '#888888',
  muted: '#9aa5ce',
};

let MA_COLORS = {};
try {
  MA_COLORS = {
    ma5: getComputedStyle(document.documentElement).getPropertyValue('--ma5') || '#fff',
    ma10: getComputedStyle(document.documentElement).getPropertyValue('--ma10') || '#f1c40f',
    ma20: getComputedStyle(document.documentElement).getPropertyValue('--ma20') || '#9b59b6',
    ma60: getComputedStyle(document.documentElement).getPropertyValue('--ma60') || '#1abc9c'
  };
} catch (e) {
  MA_COLORS = { ma5: '#fff', ma10: '#f1c40f', ma20: '#9b59b6', ma60: '#1abc9c' };
}

const ALERT_ENABLED_STORAGE_KEY = 'stock-monitor-alert-enabled';

const INDICATOR_LABELS = {
  macd_slope: 'DIF 斜率',
  dea_slope: 'DEA 斜率',
  hist_slope: '柱斜率',
  macd: 'DIF 值',
  macd_dea: 'DEA 值',
  macd_hist: '柱值',
};

const API_TO_TEST_INDICATOR = {
  macd: 'macd',
  macd_dea: 'dea',
  macd_hist: 'hist',
  macd_slope: 'macd_slope',
  dea_slope: 'dea_slope',
  hist_slope: 'hist_slope',
};

const TEST_TO_API_INDICATOR = {
  macd: 'macd',
  dea: 'macd_dea',
  hist: 'macd_hist',
  macd_slope: 'macd_slope',
  dea_slope: 'dea_slope',
  hist_slope: 'hist_slope',
};

let refreshTimer = null;
let userInteracted = false;
let userInteractionResetTimer = null;
let lastNewsTime = '';

const state = {
  config: null,
  current: null,
  calibration: null,
  hoverIndex: -1,
  selectedIndex: -1,
  initialSelectionDone: false,
  watchQuotes: {},
  currentQuote: null,
  alerts: [],
  editingAlertIndex: null,
  alertEnabledMap: {},
  alertTestResults: {},
  visibleCount: 60,
  dataOffset: 0,
  touch: {
    mode: null,
    startX: 0,
    startOffset: 0,
    startDistance: 0,
    startVisibleCount: 60,
    moved: false,
  },
};

const INTERACTION_LIMITS = {
  minVisibleCount: 10,
  maxVisibleCount: 120,
  panStepPx: 20,
};

let rafId = null;

// 全局数据结构
let _hk_price_buffer = {};
