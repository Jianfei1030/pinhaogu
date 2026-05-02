// indicators.js - 指标计算函数

function computeMA(list, window) {
  const res = new Array(list.length).fill(null);
  let sum = 0;
  for (let i = 0; i < list.length; i++) {
    const v = Number(list[i].close || 0);
    sum += v;
    if (i >= window) sum -= Number(list[i - window].close || 0);
    if (i >= window - 1) res[i] = sum / window;
  }
  return res;
}
