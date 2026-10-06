FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# The virtualenv lives outside /app so the development bind mount does not hide it.
RUN useradd --create-home --uid 1000 app && mkdir /opt/venv && chown app:app /opt/venv
WORKDIR /app
USER app

COPY --chown=app:app pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY --chown=app:app . .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
