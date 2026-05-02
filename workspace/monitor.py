# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from calibrate import CALIBRATION_STATUS_FILE, run_calibration

import pandas as pd
import yaml

from data_source import DataSourceError, fetch_realtime

# 全 A 股补全模块路径配置
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import config
from utils.push import send_both
from utils.logger import setup_logger
from utils.trading_calendar import is_trading_day
from database import get_db_path, query_kline, write_indicators
from indicators import IndicatorEngine
from indicators.macd import MACD
from services.monitor_service import build_monitor_runtime_config
from services.monitor_indicator_service import (
    build_indicator_df,
    calc_macd_with_history,
    collect_indicator_frames,
)
from services.monitor_schedule_service import (
    parse_clock,
    combine_today,
    market_sessions,
    trading_status,
    should_log_waiting,
    build_waiting_log_message,
)
from services.monitor_stock_service import (
    process_stock,
    build_stock_line,
    stock_key,
    format_volume,
    MonitorStockServiceError,
)
from services.monitor_alert_service import (
    slope_arrow,
    alert_context_from_row,
    build_rule_alert_message,
    detect_rule_alerts,
    detect_alerts,
)

ALERT_RULES = {
    "change_pct": 5.0,
    "volume_spike": 3.0,
    "macd_cross": True,
}

BAR = "─" * 50


class AlertRule:
    """单条告警规则"""

    FIELD_ALIASES = {
        "macd": "macd",
        "dea": "macd_dea",
        "hist": "macd_hist",
        "macd_dea": "macd_dea",
        "macd_hist": "macd_hist",
        "macd_slope": "macd_slope",
        "dea_slope": "macd_dea_slope",
        "hist_slope": "macd_hist_slope",
        "macd_dea_slope": "macd_dea_slope",
        "macd_hist_slope": "macd_hist_slope",
    }
    OPERATORS = {">", "<", ">=", "<=", "=="}

    def __init__(self, config: dict):
        self.name = config["name"]
        self.period = str(config["period"])
        self.conditions = config.get("conditions", [])
        if isinstance(self.conditions, list):
            self.conditions = {"logic": "AND", "rules": self.conditions}
        raw_ref_periods = config.get("ref_periods", []) or []
        if not isinstance(raw_ref_periods, list):
            raise ValueError("ref_periods must be a list")
        self.ref_periods = [str(item).strip() for item in raw_ref_periods if str(item).strip()]
        self.cooldown = int(config.get("cooldown", 300) or 300)
        self.last_triggered: float | None = None

    def evaluate(self, current: dict, prev: dict, prev_prev: dict) -> bool:
        """
        边缘触发逻辑:
        - 当前 bar 条件组满足
        - 上一根 bar 条件组满足
        - 上上一根 bar 条件组不满足
        """
        current_ok = self._eval_group(current, self.conditions)
        prev_ok = self._eval_group(prev, self.conditions)
        prev_prev_ok = self._eval_group(prev_prev, self.conditions)
        return current_ok and prev_ok and not prev_prev_ok

    def _eval_group(self, bar: dict, group: Any) -> bool:
        """递归求值条件组，兼容旧版 list 结构。"""
        if isinstance(group, list):
            return all(self._eval_group(bar, rule) for rule in group)

        if not isinstance(group, dict):
            raise ValueError("condition/group must be a dict or list")

        if "indicator" in group:
            return self._check(bar, group)

        logic = str(group.get("logic", "AND") or "AND").upper()
        rules = group.get("rules", [])
        if not isinstance(rules, list) or not rules:
            raise ValueError("condition group rules must be a non-empty list")
        if logic not in {"AND", "OR"}:
            raise ValueError(f"unsupported logic: {logic}")

        evaluator = any if logic == "OR" else all
        return evaluator(self._eval_group(bar, rule) for rule in rules)

    def _normalize_indicator(self, indicator: str) -> str:
        indicator = str(indicator).strip()
        if ":" in indicator:
            ref_period, ref_indicator = indicator.split(":", 1)
            ref_period = ref_period.strip()
            ref_indicator = ref_indicator.strip()
            normalized_ref = self.FIELD_ALIASES.get(ref_indicator)
            if not ref_period or not normalized_ref:
                raise ValueError(f"unsupported indicator: {indicator}")
            return f"{ref_period}_{normalized_ref}"

        normalized = self.FIELD_ALIASES.get(indicator)
        if normalized:
            return normalized

        legacy_match = re.match(r"^(?P<period>[A-Za-z0-9]+)_(?P<indicator>.+)$", indicator)
        if legacy_match:
            ref_indicator = legacy_match.group("indicator")
            normalized_ref = self.FIELD_ALIASES.get(ref_indicator, ref_indicator)
            return f"{legacy_match.group('period')}_{normalized_ref}"

        raise ValueError(f"unsupported indicator: {indicator}")

    def _check(self, bar: dict, condition: dict) -> bool:
        indicator = self._normalize_indicator(condition["indicator"])
        op = str(condition["op"])
        value = float(condition["value"])
        if op not in self.OPERATORS:
            raise ValueError(f"unsupported operator: {op}")

        if indicator not in bar or bar[indicator] is None:
            return False

        current = float(bar[indicator])
        if op == ">":
            return current > value
        if op == "<":
            return current < value
        if op == ">=":
            return current >= value
        if op == "<=":
            return current <= value
        return current == value

    def in_cooldown(self) -> bool:
        if self.last_triggered is None:
            return False
        return (time.time() - self.last_triggered) < self.cooldown

    def mark_triggered(self):
        self.last_triggered = time.time()



def ensure_console_utf8():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


# ---- Alert log file setup ----
_alert_logger = setup_logger("alerts", log_dir="logs")

class Monitor:
    def __init__(self, config_path: str = "config.yaml", interval: int = 30, date: str | None = None):
        # R5.1b: 使用 service 层构建运行时配置
        runtime_cfg = build_monitor_runtime_config(
            workspace=Path(__file__).resolve().parent,
            config_path=config_path,
            interval=interval,
        )
        self.workspace = runtime_cfg["workspace"]
        self.config_path = runtime_cfg["config_path"]
        self.config = runtime_cfg["config"]
        self.watchlist = runtime_cfg["watchlist"]
        self.interval = runtime_cfg["interval"]
        self.alert_rules = runtime_cfg["alert_rules"]
        self.trading_hours = runtime_cfg["trading_hours"]
        
        # 其余初始化字段保持不变
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self.running = True
        self.started_at = time.time()
        self.tick_count = 0
        self.alert_count = 0
        self.last_prices: dict[str, float] = {}
        self.last_alert_keys: set[str] = set()
        self.last_wait_log_at: float | None = None
        self.reload_file_path = self.workspace.parent / "data" / ".monitor_reload"
        self._last_reload_mtime: float = 0.0
        self.calibration_status_path = CALIBRATION_STATUS_FILE
        self.calibrated_today = ""
        self.calibrate_done = False
        self.backfill_done: set[tuple[str, str]] = set()  # 已执行的补全时段 {(date_str, "16:30")}
        self._backfill_last_date: str = ""  # 上次触发补全的日期

        self.engine = IndicatorEngine()
        self.engine.register(MACD())

        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

    def _resolve_path(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.workspace / candidate

    def _load_config(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _load_alert_rules(self, config: dict[str, Any]) -> list[AlertRule]:
        raw_alerts = config.get("alerts", [])
        if isinstance(raw_alerts, dict):
            return []
        return [AlertRule(item) for item in raw_alerts if isinstance(item, dict)]

    def _check_reload(self) -> None:
        """检查是否有来自 server.py 的重载请求"""
        try:
            if not self.reload_file_path.exists():
                return
            mtime = self.reload_file_path.stat().st_mtime
            if mtime > self._last_reload_mtime:
                self._last_reload_mtime = mtime
                self._reload_config()
        except Exception:
            pass  # 忽略文件系统错误

    def _reload_config(self) -> None:
        """重新加载 config.yaml 并更新告警规则"""
        try:
            new_config = self._load_config(self.config_path)
            self.config = new_config
            self.watchlist = new_config.get("watchlist", [])
            self.alert_rules = self._load_alert_rules(new_config)
            self.trading_hours = self._load_trading_hours(new_config)
            print(f"[reload] 配置已重载，告警规则：{len(self.alert_rules)} 条")
            sys.stdout.flush()
        except Exception as exc:
            print(f"[reload] 重载配置失败：{exc}")
            sys.stdout.flush()

    def _load_trading_hours(self, config: dict[str, Any]) -> dict[str, dict[str, str]]:
        trading_hours = config.get("trading_hours", {})
        if not isinstance(trading_hours, dict):
            return {}
        return {str(market).upper(): value for market, value in trading_hours.items() if isinstance(value, dict)}

    def _parse_clock(self, value: str) -> tuple[int, int]:
        """Thin wrapper around service.parse_clock"""
        return parse_clock(value)

    def _combine_today(self, now: datetime, value: str) -> datetime:
        """Thin wrapper around service.combine_today"""
        return combine_today(now, value)

    def _market_sessions(self, market: str, now: datetime) -> list[tuple[datetime, datetime]]:
        """Thin wrapper around service.market_sessions"""
        return market_sessions(self.trading_hours, market, now)

    def _trading_status(self, now: datetime | None = None) -> dict[str, Any]:
        """Thin wrapper around service.trading_status"""
        return trading_status(self.trading_hours, now, self.watchlist)


    def _should_log_waiting(self, now_ts: float) -> bool:
        """Thin wrapper around service.should_log_waiting"""
        return should_log_waiting(self.last_wait_log_at, now_ts, interval_seconds=1800.0)

    def _log_waiting(self, status: dict[str, Any]):
        """Keep logger behavior, delegate message building to service"""
        now_ts = time.time()
        if self._should_log_waiting(now_ts):
            message = build_waiting_log_message(status, self._format_watchlist())
            print(message)
            sys.stdout.flush()
            self.last_wait_log_at = now_ts

    def _project_root(self) -> Path:
        return self.workspace.parent

    def _db_path(self, stock: dict[str, Any]) -> str:
        relative = get_db_path(stock["market"], stock["symbol"], self.date)
        return str((self._project_root() / relative).resolve())

    def _stock_key(self, stock: dict[str, Any]) -> str:
        return f"{str(stock['market']).upper().strip()}{str(stock['symbol']).strip()}"

    def _format_watchlist(self) -> str:
        return ", ".join(f"{self._stock_key(stock)}({stock.get('name', '')})" for stock in self.watchlist)

    def _build_indicator_df(self, rows: list[dict]) -> pd.DataFrame:
        """Thin wrapper around monitor_indicator_service.build_indicator_df"""
        return build_indicator_df(rows)

    def _calc_macd(self, db_path: str, table: str = "kline_15min") -> pd.DataFrame:
        """Thin wrapper around monitor_indicator_service.calc_macd_with_history"""
        return calc_macd_with_history(db_path, table, engine=self.engine)

    def _collect_indicator_frames(self, db_path: str) -> dict[str, pd.DataFrame]:
        """Thin wrapper around monitor_indicator_service.collect_indicator_frames"""
        return collect_indicator_frames(
            db_path,
            base_period="15min",
            ref_periods=[],
            alert_rules=self.alert_rules,
            engine=self.engine,
        )

    def _format_volume(self, value: float | int) -> str:
        value = float(value or 0)
        if value >= 100_000_000:
            return f"{value / 100_000_000:.2f}亿"
        if value >= 10_000:
            return f"{value / 10_000:.1f}万"
        return f"{value:.0f}"

    def _series_value(self, row: pd.Series, key: str) -> float:
        value = row.get(key)
        if value is None or pd.isna(value):
            return 0.0
        return float(value)

    def _alert_context_from_row(
        self,
        stock: dict[str, Any],
        realtime: dict[str, Any],
        row: pd.Series,
    ) -> dict[str, Any]:
        """Thin wrapper around monitor_alert_service.alert_context_from_row"""
        return alert_context_from_row(
            row=row,
            period="15min",  # period not used in context building
            symbol=stock.get("symbol", ""),
            market=stock.get("market", ""),
            stock_name=stock.get("name"),
            realtime=realtime,
        )

    def _slope_arrow(self, value: float) -> str:
        """Thin wrapper around monitor_alert_service.slope_arrow"""
        return slope_arrow(value)

    def _build_rule_alert_message(self, rule: AlertRule, context: dict[str, Any]) -> str:
        """Thin wrapper around monitor_alert_service.build_rule_alert_message"""
        return build_rule_alert_message(rule, context)

    def _send_alert(self, alert_message: str):
        """推送到 Telegram + QQ"""
        tg_ok, qq_ok = send_both(alert_message)
        if tg_ok:
            print("  Telegram 推送成功")
        else:
            print("  Telegram 推送失败")
        if qq_ok:
            print("  QQ 推送成功")
        else:
            print("  QQ 推送失败")

    def _detect_rule_alerts(
        self,
        stock: dict[str, Any],
        indicator_frames: dict[str, pd.DataFrame],
        realtime: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        Thin wrapper around monitor_alert_service.detect_rule_alerts.
        
        Keeps self.last_alert_keys update semantics and edge-trigger/cool-down logic.
        """
        alerts: list[dict[str, str]] = []
        stock_code = self._stock_key(stock)

        for rule in self.alert_rules:
            indicator_df = indicator_frames.get(rule.period)
            if indicator_df is None or len(indicator_df) < 3:
                continue

            current_row = indicator_df.iloc[-1]
            prev_row = indicator_df.iloc[-2]
            prev_prev_row = indicator_df.iloc[-3]
            current = current_row.to_dict()
            prev = prev_row.to_dict()
            prev_prev = prev_prev_row.to_dict()

            if not rule.evaluate(current, prev, prev_prev):
                continue
            if rule.in_cooldown():
                continue

            context = self._alert_context_from_row(stock, realtime, current_row)
            # 价格无效（0 或负数）时不发告警，避免开盘初瞬时数据异常
            if context['price'] <= 0:
                continue
            alert_message = self._build_rule_alert_message(rule, context)
            alert_key = f"{stock_code}:rule:{rule.name}:{rule.period}:{context['bar_time']}"
            alerts.append({
                "type": "rule",
                "key": alert_key,
                "message": alert_message,
            })
            rule.mark_triggered()

        return alerts

    def _detect_alerts(
        self,
        stock: dict[str, Any],
        intraday_rows: list[dict],
        indicator_frames: dict[str, pd.DataFrame],
        realtime: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        Hybrid approach: keep legacy change_pct/macd_cross detection,
        but delegate rule-based alerts to monitor_alert_service.detect_rule_alerts.
        
        Keeps self.last_alert_keys update semantics, cool-down and dedup logic unchanged.
        """
        alerts: list[dict[str, str]] = []
        stock_code = self._stock_key(stock)
        current_price = float(realtime.get("current") or 0)
        open_price = float(realtime.get("open") or 0)
        current_time = intraday_rows[-1]["bar_time"] if intraday_rows else "--:--"
        indicator_df = indicator_frames.get("15min", pd.DataFrame())

        # 价格无效（0 或负数）时不检测告警，避免开盘初瞬时数据异常
        if current_price <= 0:
            return alerts

        if open_price > 0:
            change_vs_open = (current_price - open_price) / open_price * 100
            if abs(change_vs_open) >= ALERT_RULES["change_pct"]:
                direction = "上涨" if change_vs_open > 0 else "下跌"
                alerts.append(
                    {
                        "type": "change_pct",
                        "key": f"{stock_code}:change_pct:{current_time}:{direction}",
                        "message": f"{stock_code} {direction}{change_vs_open:.2f}% @{current_time}",
                    }
                )

        if len(intraday_rows) >= 21:
            latest_volume = float(intraday_rows[-1].get("volume") or 0)
            avg_volume = pd.Series([float(row.get("volume") or 0) for row in intraday_rows[-21:-1]]).mean()
        if ALERT_RULES["macd_cross"] and len(indicator_df) >= 2:
            prev_row = indicator_df.iloc[-2]
            curr_row = indicator_df.iloc[-1]
            prev_hist = float(prev_row.get("macd_hist") or 0)
            curr_hist = float(curr_row.get("macd_hist") or 0)
            cross_time = str(curr_row.get("bar_time", current_time))
            if curr_hist > 0 >= prev_hist:
                alerts.append(
                    {
                        "type": "macd_cross",
                        "key": f"{stock_code}:macd_gold:{cross_time}",
                        "message": f"{stock_code} MACD 金叉 @{cross_time}",
                    }
                )
            elif curr_hist < 0 <= prev_hist:
                alerts.append(
                    {
                        "type": "macd_cross",
                        "key": f"{stock_code}:macd_dead:{cross_time}",
                        "message": f"{stock_code} MACD 死叉 @{cross_time}",
                    }
                )

        # Delegate rule-based alerts to service layer
        alerts.extend(self._detect_rule_alerts(stock, indicator_frames, realtime))

        fresh_alerts = [alert for alert in alerts if alert["key"] not in self.last_alert_keys]
        for alert in fresh_alerts:
            self.last_alert_keys.add(alert["key"])
        self.alert_count += len(fresh_alerts)
        return fresh_alerts

    def _render_line(
        self,
        stock: dict[str, Any],
        realtime: dict[str, Any],
        indicator_df: pd.DataFrame,
        intraday_rows: list[dict],
    ) -> str:
        now_text = datetime.now().strftime("%H:%M:%S")
        stock_code = self._stock_key(stock)
        name = stock.get("name", "")
        price = float(realtime.get("current") or 0)
        prev_close = float(realtime.get("prev_close") or 0)
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else float(realtime.get("change_pct") or 0)

        macd_text = "MACD:-- DEA:-- -"
        if not indicator_df.empty:
            last = indicator_df.iloc[-1]
            dea = float(last.get("macd_dea") or 0)
            dea_prev = float(indicator_df.iloc[-2].get("macd_dea") or 0) if len(indicator_df) >= 2 else dea
            arrow = "↑" if dea >= dea_prev else "↓"
            macd_text = f"MACD:{float(last.get('macd') or 0):.2f} DEA:{dea:.2f} {arrow}"

        latest_volume = intraday_rows[-1].get("volume", 0) if intraday_rows else 0
        return (
            f"[{now_text}] {stock_code} {name} | {price:.2f} | {change_pct:+.2f}% | "
            f"{macd_text} | Vol: {self._format_volume(latest_volume)}"
        )

    def _handle_stock(
        self,
        stock: dict[str, Any],
        realtime: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """
        处理单只股票：委托给 process_stock(service 层)。
        
        保留的本地语义：
        - 更新 self.last_prices
        - 返回 (line, alerts) 保持 tick() 调用兼容
        """
        db_path = self._db_path(stock)
        
        # 委托给 service 层
        line, alerts, meta = process_stock(
            stock=stock,
            realtime=realtime or {},
            db_path=db_path,
            collect_indicator_frames_fn=self._collect_indicator_frames,
            detect_alerts_fn=self._detect_alerts,
            last_alert_keys=self.last_alert_keys,
        )
        
        # 保留更新 last_prices 的语义
        if meta.get("has_data") and realtime:
            current_price = float(realtime.get("current") or 0)
            if current_price > 0:
                self.last_prices[self._stock_key(stock)] = current_price
        
        return line, alerts

    def check_calibration_trigger(self):
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        if not is_trading_day():  # 非交易日不执行
            return
        # 矫正已禁用：监控和矫正使用相同腾讯 1 分钟数据源，无需重复
        return
        if (now.hour, now.minute) < (16, 30):
            return
        if self.calibrated_today == date_str and self.calibrate_done:
            return

        self.calibrated_today = date_str
        try:
            results = run_calibration(self.watchlist, date_str)
            self.calibrate_done = True
            print(f"[CALIBRATE] 矫正完成：{results}")

        except Exception as exc:
            self.calibrate_done = False
            print(f"[CALIBRATE] 矫正失败：{exc}")
        finally:
            sys.stdout.flush()

    def _run_daily_backfill_all(self):
        """每日全 A 股增量补全（16:30 触发）"""
        from daily_incremental_backfill import run as run_daily_backfill

        logger = logging.getLogger("monitor")
        logger.info("[BACKFILL] 开始全 A 股日线补全...")
        try:
            # 调用 run() 而非 main()，避免 argparse 冲突导致 monitor 退出
            run_daily_backfill(
                date=datetime.now().strftime("%Y-%m-%d"),
                dry_run=False,
                notify=True,
            )
            logger.info("[BACKFILL] 全 A 股日线补全完成")
        except Exception as e:
            logger.error(f"[BACKFILL] 全 A 股补全失败：{e}")
            # 失败时推送 Telegram+QQ 报告
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            fail_msg = (
                f"❌ 全 A 股日线补全失败\n\n"
                f"触发时间：{now_str}\n"
                f"错误信息：{e}\n"
                f"涉及股票数：5,497+ 只\n"
            )
            try:
                tg_ok, qq_ok = send_both(fail_msg)
                logger.info(f"[BACKFILL] 失败报告推送: Telegram={'OK' if tg_ok else 'FAIL'}, QQ={'OK' if qq_ok else 'FAIL'}")
            except Exception as push_err:
                logger.error(f"[BACKFILL] 失败报告推送异常：{push_err}")

    def _check_backfill_trigger(self):
        """每日 16:30 / 20:30 触发一次数据补全：
        1. 全 A 股日线补全（5,497 只）
        2. 监控标的补全（5 只）
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        # 跨日期时清空 backfill_done，确保新一天能重新触发
        if self._backfill_last_date and self._backfill_last_date != date_str:
            self.backfill_done.clear()
        self._backfill_last_date = date_str

        if not is_trading_day():  # 非交易日不执行  # 周末不执行
            return

        # 16:30 触发
        if now.hour == 16 and now.minute >= 30:
            trigger_key = (date_str, "16:30")
            if trigger_key not in self.backfill_done:
                self.backfill_done.add(trigger_key)
                print("[BACKFILL] 开始每日数据补全 (16:30)...")
                sys.stdout.flush()

                try:
                    # Step 1: 全 A 股补全
                    self._run_daily_backfill_all()

                    # Step 2: 监控标的补全
                    self._run_backfill()

                    print("[BACKFILL] 每日数据补全完成 (16:30)")
                except Exception as e:
                    print(f"[BACKFILL] 数据补全失败：{e}")
                finally:
                    sys.stdout.flush()

        # 20:30 兜底触发（仅当 16:30 未执行时）
        if now.hour == 20 and now.minute >= 30:
            trigger_key_1630 = (date_str, "16:30")
            if trigger_key_1630 in self.backfill_done:
                return  # 16:30 已执行，跳过

            trigger_key = (date_str, "20:30")
            if trigger_key not in self.backfill_done:
                self.backfill_done.add(trigger_key)
                print("[BACKFILL] 16:30 未触发，开始兜底数据补全 (20:30)...")
                sys.stdout.flush()

                try:
                    # Step 1: 全 A 股补全
                    self._run_daily_backfill_all()

                    # Step 2: 监控标的补全
                    self._run_backfill()

                    print("[BACKFILL] 兜底数据补全完成 (20:30)")
                except Exception as e:
                    print(f"[BACKFILL] 数据补全失败：{e}")
                finally:
                    sys.stdout.flush()

    def _run_backfill(self):
        """拉取各周期最大范围数据，写入 DB。"""
        from data_source import fetch_kline
        from aggregator import aggregate_120min
        from database import init_db, upsert_kline, upsert_chip_distribution
        import sys

        for stock in self.watchlist:
            market = str(stock.get("market", "HK")).upper().strip()
            symbol = stock["symbol"]
            db_path = self._db_path(stock)
            init_db(db_path)

            for period in ("5min", "15min", "30min", "60min", "1d", "1wk"):
                rows = fetch_kline(symbol, market, period, count=9999)
                if rows:
                    upsert_kline(db_path, f"kline_{period}", rows)

            # 120min 从 60min 聚合
            rows_60 = fetch_kline(symbol, market, "60min", count=9999)
            if rows_60:
                rows_120 = aggregate_120min(rows_60)
                if rows_120:
                    upsert_kline(db_path, "kline_120min", rows_120)

            # 筹码分布（港股/日线级别）
            try:
                from calc_chip_dist import calc_chip_distribution
                # 格式化 symbol 给 yfinance 用
                if market == "HK":
                    pure = symbol.lstrip("0")
                    if len(pure) < 4:
                        pure = pure.zfill(4)
                    yf_symbol = f"{pure}.HK"
                elif market == "A":
                    yf_symbol = f"{symbol}.SS" if symbol.startswith(("6", "9")) else f"{symbol}.SZ"
                else:
                    yf_symbol = symbol
                chip = calc_chip_distribution(yf_symbol, days=90)
                if chip:
                    upsert_chip_distribution(db_path, chip)
                    print(f"  [CHIP] {symbol}: 获利{chip['profit_ratio']*100:.1f}%, 成本{chip['avg_cost']:.2f}")
            except Exception as e:
                print(f"  [CHIP] {symbol} 计算失败：{e}")
            sys.stdout.flush()

    def tick(self):
        self.tick_count += 1
        self.last_wait_log_at = None
        self._check_reload()
        print(BAR)
        for stock in self.watchlist:
            try:
                market = str(stock.get("market", "HK")).upper().strip()
                realtime = fetch_realtime(stock["symbol"], market)
                line, alerts = self._handle_stock(stock, realtime=realtime)
                print(line)
                for alert in alerts:
                    print(f"  ⚠️ ALERT: {alert['message']}")
                    if alert.get("type") == "rule":
                        self._send_alert(alert["message"])
                        
                    _alert_logger.info("ALERT: %s | %s", alert.get("type", "unknown"), alert["message"])
            except (DataSourceError, RuntimeError, OSError, ValueError) as exc:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {self._stock_key(stock)} ERROR: {exc}")
        self.write_status()
        sys.stdout.flush()

    def write_status(self):
        """写状态文件，供 server.py 和页面读取"""
        calibration = {}
        try:
            if self.calibration_status_path.exists():
                calibration = json.loads(self.calibration_status_path.read_text(encoding="utf-8"))
        except Exception:
            calibration = {}

        status = {
            "pid": os.getpid(),
            "start_time": datetime.fromtimestamp(self.started_at).strftime("%Y-%m-%d %H:%M:%S"),
            "last_tick": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tick_count": self.tick_count,
            "alert_count": self.alert_count,
            "last_prices": self.last_prices,
            "watchlist": [s["symbol"] for s in self.watchlist],
            "calibration": calibration,
        }
        data_dir = self.workspace.parent / "data"
        data_dir.mkdir(exist_ok=True)
        status_path = data_dir / ".monitor_status.json"
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self):
        print("🐾 股票监控引擎 v1.0")
        print(f"Watchlist: {self._format_watchlist()}")
        print(f"Interval: {self.interval}s")
        if self.alert_rules:
            print("Rule Alerts:", ", ".join(f"{rule.period}:{rule.name}" for rule in self.alert_rules))
        print(BAR)
        initial_status = self._trading_status()
        if not initial_status["active"] and initial_status.get("next_open"):
            wait_seconds = (initial_status["next_open"] - datetime.now()).total_seconds()
            if wait_seconds > 1800:
                print(f"非交易时段，等待中...下次开盘：{initial_status['next_open'].strftime('%H:%M')}")
                self.last_wait_log_at = time.time()
        sys.stdout.flush()

        while self.running:
            started = time.time()
            self.check_calibration_trigger()
            status = self._trading_status()
            if status["active"]:
                self.tick()
            else:
                self.write_status()
                self._log_waiting(status)
            self._check_backfill_trigger()
            elapsed = time.time() - started
            if not self.running:
                break
            time.sleep(max(0, self.interval - elapsed))

        self.print_summary()

    def _handle_stop(self, signum, frame):  # noqa: ANN001, ARG002
        if self.running:
            self.running = False
            print("\nMonitoring stopped")
            sys.stdout.flush()

    def print_summary(self):
        duration = int(time.time() - self.started_at)
        if duration >= 3600:
            duration_text = f"{duration // 3600}小时{(duration % 3600) // 60}分钟"
        elif duration >= 60:
            duration_text = f"{duration // 60}分钟"
        else:
            duration_text = f"{duration}秒"
        print(f"📊 运行摘要：运行{duration_text} | tick: {self.tick_count}次 | 告警：{self.alert_count}次")
        sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="股票实时监控引擎")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径，默认 config.yaml")
    parser.add_argument("--interval", type=int, default=30, help="刷新间隔秒数，默认 30")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="目标日期，默认今天")
    return parser.parse_args()


def main():
    ensure_console_utf8()
    args = parse_args()
    monitor = Monitor(config_path=args.config, interval=args.interval, date=args.date)
    monitor.run()


if __name__ == "__main__":
    main()
