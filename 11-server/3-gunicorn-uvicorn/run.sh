#!/bin/bash
# 출처: 풀스택 베이스 템플릿 (2026.04~) — 로컬 개발 실행. 운영은 systemd 유닛(fastapi.service)이 같은 app.main:app 을 Gunicorn 으로 띄운다
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
