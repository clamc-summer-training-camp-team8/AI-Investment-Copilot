FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        curl \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY analytics ./analytics
COPY app ./app
COPY contracts ./contracts
COPY scripts ./scripts
# 在线服务只携带已冻结、受治理的行情副本；AKShare/Tushare 采集依赖不进入镜像。
COPY real_data/quant ./real_data/quant
# 共享集成环境使用的虚构样例数据。受限原件和 real_data/raw 均不进入镜像；
# .dockerignore 也会继续排除 docx/pdf/xlsx 等交付附件。
COPY docs/data/数据分析交付包/业务样例包 ./docs/data/数据分析交付包/业务样例包

RUN addgroup --system copilot \
    && adduser --system --ingroup copilot --home /app copilot \
    && mkdir -p /app/storage \
    && chown -R copilot:copilot /app/storage

USER copilot

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
