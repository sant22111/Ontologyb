#!/usr/bin/env bash
cd "$(dirname "$0")"
pip install -q -r requirements.txt
python3 -m uvicorn app:app --host 127.0.0.1 --port 8100
