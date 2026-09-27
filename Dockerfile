FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.7.5
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY examples ./examples
RUN uv sync --frozen --no-dev && mkdir -p .runtime && chown -R 10001:10001 /app
USER 10001
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "anlan.interfaces.serve", "--config", "/app/config/service.json", "--host", "0.0.0.0"]
