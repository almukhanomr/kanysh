# Development recipe, NOT validated/pinned-by-digest. Do not publish as a supported solver image.
FROM python:3.12.14-slim
WORKDIR /opt/kanysh-basic
RUN pip install --no-cache-dir uv==0.13.1
COPY pyproject.toml uv.lock README.md LICENSE NOTICE THIRD_PARTY.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra ui --extra viewer
ENV OPENSUBSURFACE_HOME=/data
CMD [".venv/bin/kanysh-basic", "serve", "--ui", "--port", "8765"]
