# One image, two interpreters: /opt/gil runs StarPulse on CPython 3.14 and /opt/ft on its free-threaded build (3.14t),
# from the same lockfile, so a run on each differs only in the interpreter. /opt/gil also holds the bench group, whose
# Locust drives both. Build from the repository root:
#
#     docker build -f bench/free_threading/Dockerfile -t starpulse-free-threading .
FROM debian:trixie-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1
RUN uv python install 3.14 3.14t
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY starpulse starpulse
RUN UV_PROJECT_ENVIRONMENT=/opt/gil uv sync --frozen --no-editable --no-default-groups --group bench --python 3.14 \
    && UV_PROJECT_ENVIRONMENT=/opt/ft uv sync --frozen --no-editable --no-default-groups --python 3.14t
# Locust reads only /api routes, and serve refuses to start without a built page, so each venv gets a placeholder one.
RUN for package in /opt/*/lib/python3.14*/site-packages/starpulse; do \
      mkdir -p "$package/static" && echo "<!doctype html>" >"$package/static/index.html"; done
COPY bench bench
