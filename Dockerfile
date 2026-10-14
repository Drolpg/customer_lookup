# ---------- Estágio 1: dependências com uv ----------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Camada só de dependências: fica em cache enquanto uv.lock não mudar.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- Estágio 2: runtime enxuto, sem uv nem cache ----------
FROM python:3.14-slim

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
USER app

EXPOSE 8000 9000

# A mesma imagem roda api, worker e externo; o compose define o comando de cada um.
CMD ["uvicorn", "customer_lookup.main:app", "--host", "0.0.0.0", "--port", "8000"]
