#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
source .env 2>/dev/null || true
python status_report.py
