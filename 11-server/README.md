# 11. 서버 런타임과 운영 표준

Django + uWSGI 로 시작한 서버를 Django · FastAPI 공존 → FastAPI 단독 → Gunicorn + Uvicorn systemd 유닛과 Nginx 표준 설정으로 바꿔 온 과정이다.

## 흐름
| 단계 | 시기 | 프로젝트 | 방식 |
|---|---|---|---|
| 1 | 2025.02~04 | AI 상담 챗봇 서비스 (초기 Django 계열) | Django + uWSGI. 서버 호스트명으로 운영 · 로컬 분기, 자격증명이 코드 안에 |
| 2 | 2025.04~09 | AI 상담 챗봇 서비스 (Django + FastAPI 계열) | Django(8000) 와 FastAPI(8001) 공존, Nginx 가 경로로 분기 |
| 3 | 2025.11~2026.02 | AI 캐릭터 대화 서비스 → 풀스택 베이스 템플릿 | FastAPI 단독. Gunicorn 마스터 + UvicornWorker, systemd 유닛 2종(웹 · 워커) |
| 4 | 2026~ | 풀스택 베이스 템플릿 | Nginx 전역 · 사이트 설정 표준(타임아웃 · 요청 제한 · 캐시 · 보안 헤더) |

## 1. Django + uWSGI  →  `1-uwsgi-django/`
**어디서** AI 상담 챗봇 서비스 (초기 Django 계열) · 2025.02~04
**문제** WSGI 는 요청 하나가 응답을 끝낼 때까지 워커를 잡는 동기 방식이다. 모델 응답을 실시간으로 흘려보내야 하는 챗봇에서 스트리밍도 WebSocket 도 쓸 수 없었고, 그래서 청크를 세션에 쌓고 화면이 폴링하는 우회가 생겼다. 운영 · 로컬 구분은 서버 호스트명이 EC2 규칙으로 시작하는지로 판정했고, DB 비밀번호와 시크릿 키가 설정 파일 안에 그대로 있었다. 두 분기가 결국 같은 운영 DB 를 가리키고 있어 분기의 의미도 흐렸다.
**바꾼 것** 이 단계에서는 구조를 바꾸지 못했다. 며칠 안에 위젯을 납품하는 일정이었고, 이 경험이 다음 단계에서 비동기 서버를 붙이는 이유가 됐다.
**결과** "환경을 고르는 기준(호스트명)" 과 "환경별 값(자격증명)" 을 떼어 놓아야 한다는 것, 실시간 응답에는 동기 진입점이 맞지 않는다는 것을 배웠다.
**코드** `settings.py` — 호스트명 분기와 DB 설정 반복(자격증명은 환경변수 참조로 바꿈) / `wsgi.py` — 동기 진입점 / `uwsgi.ini` — 소켓으로 Nginx 에 붙는 uWSGI 설정

## 2. Django · FastAPI 공존  →  `2-dual-runtime/`
**어디서** AI 상담 챗봇 서비스 (Django + FastAPI 계열) · 2025.04~09
**문제** 관리자 화면과 위젯 HTML 은 Django 템플릿에 묶여 있어 한 번에 갈아엎을 수 없었다. 그러나 대화 응답만은 진짜 스트리밍이 필요했다.
**바꾼 것** 같은 코드 트리에 FastAPI 를 하나 더 두고 8001 포트로 띄웠다. Nginx 가 대화 API 접두사만 FastAPI 로, 나머지는 Django 로 보낸다. 두 프레임워크가 같은 MySQL 테이블을 다루므로 FastAPI 쪽은 SQLAlchemy 모델로 같은 테이블을 다시 선언했다. 로컬에서는 docker-compose 로 둘을 나란히 올려 확인했다. FastAPI 는 ASGI 라 이때 SSE 스트리밍을 처음 도입했다.
**결과** 스트리밍은 해결됐지만, 같은 컬럼을 두 ORM 이 다르게 선언하거나 한쪽에만 정의된 테이블이 마이그레이션에서 빠지는 일이 생겼다. 단일 스택으로 합쳐야 한다는 판단의 근거가 됐다.
**코드** `docker-compose.yml` — Django 8000 · FastAPI 8001 을 한 이미지로 띄우는 로컬 구성 / `main.py` — Django 옆에 붙인 FastAPI 진입점과 경로 접두사 / `nginx.conf` — 접두사만 8001 로 보내는 경로 분기

## 3. Gunicorn + UvicornWorker  →  `3-gunicorn-uvicorn/`
**어디서** AI 캐릭터 대화 서비스 → 풀스택 베이스 템플릿 · 2025.11~2026.02
**문제** FastAPI 단독으로 옮긴 뒤 Uvicorn 을 그대로 띄우면 프로세스 관리(죽으면 다시 올리기, 부팅 시 시작)가 없었다. 이미지 · 음성 생성처럼 1~2분 걸리는 일은 웹 프로세스 안에서 돌릴 수 없어 워커 프로세스가 따로 필요했다.
**바꾼 것** Gunicorn 을 마스터로 두고 UvicornWorker 로 FastAPI 를 돌리는 systemd 유닛과, Celery 워커 유닛 두 개를 표준으로 정했다. 옵션마다 이유가 있다. timeout 0 은 SSE · WebSocket 장기 연결이 워커 재시작으로 끊기지 않게, forwarded-allow-ips 는 로드밸런서가 붙인 프로토콜 헤더를 믿어 secure 쿠키와 https 리다이렉트가 맞게, workers 1 은 프로세스 메모리에 두는 세션 · 룸 상태가 워커 간에 갈리지 않게, capture-output 은 워커의 표준 출력까지 한 파일로 모으게 한다. 두 유닛 모두 Restart=always 로 죽으면 3초 뒤 다시 오르고, 표준 출력은 각자 다른 파일에 붙여 쓴다. 파이썬 의존성은 uv 로 만든 가상환경을 PATH 에 넣어 쓴다.
**결과** 배포는 코드를 받고 유닛을 재시작하는 한 줄이 됐다. 로컬은 여전히 Uvicorn 한 줄이라 개발과 운영의 진입점(app.main:app)이 같다.
**코드** `fastapi.service` — 옵션별 이유가 주석으로 달린 웹 유닛 / `celery.service` — Redis 뒤에 뜨는 워커 유닛, 반복 배치 스케줄러 포함 / `run.sh` — 로컬 개발 실행 한 줄

## 4. Nginx 표준  →  `4-nginx-standard/`
**어디서** 풀스택 베이스 템플릿 · 2026~
**문제** 프로젝트마다 Nginx 를 손으로 만지다 보니 같은 사고가 반복됐다. 프록시 타임아웃이 로드밸런서 유휴 시간(300초)과 달라 긴 요청이 502 로 끊겼고, 실제 클라이언트 IP 를 복원하지 않아 요청 제한이 로드밸런서 IP 하나에 걸렸다. 배포 직후 브라우저가 옛 진입 HTML 로 새 자산을 가리켜 화면이 깨졌고, 봇이 .env 같은 경로를 훑었다.
**바꾼 것** 전역 설정과 사이트 설정을 표준으로 고정했다. 전역에는 VPC 대역에서 온 X-Forwarded-For 로 실제 IP 복원, 요청 제한 존(API 10r/s · 인증 5r/s, 초과 429), 백엔드 keepalive 커넥션 풀, WebSocket Upgrade 분기, gzip 5, 버전 숨김, 업로드 600M 을 둔다. 사이트에는 타임아웃 300, 보안 헤더(SAMEORIGIN · nosniff · Referrer-Policy · Permissions-Policy), 봇 UA 와 민감 파일 차단, SPA 캐시 정책(진입 HTML no-store · 빌드 자산 1년 immutable · 업로드 7일) 을 둔다. 캐시 정책은 경로 map 하나로 server 블록에서 헤더를 한 번만 붙여, location 안에서 add_header 를 쓰면 상위 헤더가 사라지는 함정을 피했다. iframe 으로 임베드되는 위젯은 X-Frame-Options 대신 CSP frame-ancestors 로 허용 도메인을 나열한다. 변경은 문법 검사 뒤 reload 한다.
**결과** 새 프로젝트는 도메인과 경로만 바꿔 같은 설정을 쓴다. DB 스키마 변경도 마이그레이션 스크립트 하나로 순서를 강제해, 갈라진 head 나 빈 리비전이 운영에 올라가지 않는다.
**코드** `nginx.conf` — real_ip · limit_req 존 · keepalive · 캐시 map · gzip / `site.conf` — 보안 헤더 · 차단 · 경로별 프록시와 SPA 진입 / `migrate.sh` — head 병합 → DB 최신화 → 리비전 → 빈 리비전 삭제 → 적용

## 배포 방식
배포는 서버에 SSH 로 들어가 저장소를 받고 유닛을 재시작하는 수동 방식에서 시작했다(저장소 접근은 읽기 전용 Deploy Key). 이후 빌드는 서버 밖에서 하고 산출물만 서버로 올려 재시작하는 쪽으로 정리했고, 고객사 계정으로 넘기는 프로젝트는 설정을 마친 서버 이미지를 그대로 인수하는 방식을 쓴다.

## 지금 기준
FastAPI 단독, Gunicorn 마스터 + UvicornWorker 를 systemd 유닛(fastapi.service)으로, 배치 · 생성 작업은 Celery 워커 유닛(celery.service)으로 띄운다. 두 유닛 모두 Restart=always, 표준 출력은 각자 파일에 붙여 쓰고 회전은 logrotate 가 맡는다. Nginx 는 전역 · 사이트 표준 설정을 그대로 쓰고 도메인 · 경로만 바꾼다. 로컬 실행은 run.sh 한 줄, 스키마 변경은 migrate.sh 한 줄이다. 환경 선택은 호스트명, 환경별 값은 .env 에서 읽는다.
