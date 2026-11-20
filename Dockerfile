# FRNC · 프랜차이즈 창업 전 10초 리스크 체크
# 서버 이미지 — 표준 라이브러리만 쓰므로 패키지 설치 단계가 없습니다.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="FRNC" \
      org.opencontainers.image.description="Korean franchise disclosure / contract risk check (web UI + JSON API + MCP)" \
      org.opencontainers.image.version="0.1.3"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8787 \
    FRNC_DB=/app/data/app.sqlite

WORKDIR /app

RUN adduser --quiet --disabled-password --shell /usr/sbin/nologin --uid 10001 app \
    && mkdir -p /app/data

COPY --chown=app:app src/ /app/src/
# 법령 실조회 결과·공정위 API 실측 결과를 함께 넣는다. 서버는 이 파일로 조문 인용과
# 활용신청 주소를 만든다(런타임에 법령 API 를 부르지 않는다).
COPY --chown=app:app law-verification.json api-verification-*.json server.json /app/

RUN chown -R app:app /app/data
USER app

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8787')+'/healthz', timeout=4)"

# 인증키가 없어도 서버는 100% 동작합니다(브랜드 조회만 내장 샘플).
CMD ["python", "-m", "franchise_kr.server"]
