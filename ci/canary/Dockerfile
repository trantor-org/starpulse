# The canary image: boots a copy of live state from the PR head and checks its happy path, with no network. Build from
# the StarPulse checkout root once the page is built (`starpulse/static` is gitignored and is packaged from the checkout;
# `Dockerfile.dockerignore` keeps `.venv` out of the context):
#
#     pnpm --filter @starpulse/web build
#     docker build -f ci/canary/Dockerfile --build-context vendor=<trantor>/vendor -t starpulse-canary .
#
# The image runs free-threaded CPython 3.14t, as live does. aioquic and pylsqpack (hypercorn[h3]) publish no 3.14t wheel
# and their sdists fail to build there, so `vendor` is a directory holding trantor's patched `aioquic` and `pylsqpack`
# copies; the locked requirements are exported and those two lines point at it.
#
# Run it with `--network none`, the live config and machines read-only, and the store copy read-write as /work/history.sqlite.
# Mount the config directory at the same depth under /live as under <live> (`<config-dir>` is `infrastructure/<host>`), since the
# config reads its board and machines by relative path:
#
#     docker run --rm --network none -v <live>/<config-dir>:/live/<config-dir>:ro \
#       -v <live>/.starpulse:/live/.starpulse:ro -v <copy>:/work/history.sqlite starpulse-canary \
#       --url http://127.0.0.1:8766 --config /live/<config-dir>/starpulse.toml \
#       --machines /live/.starpulse/machines --db /work/history.sqlite
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1
ENV PATH=/opt/canary/bin:/usr/local/bin:/usr/bin:/bin
RUN uv python install 3.14t
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY starpulse starpulse
COPY --from=vendor / /vendor
RUN uv export --frozen --no-hashes --no-emit-project --no-default-groups --group bench --no-header -o locked.txt \
    && sed -i -e 's|^aioquic==.*|aioquic @ file:///vendor/aioquic|' -e 's|^pylsqpack==.*|pylsqpack @ file:///vendor/pylsqpack|' locked.txt \
    && grep -q '^aioquic @' locked.txt && grep -q '^pylsqpack @' locked.txt \
    && uv venv --python 3.14t /opt/canary \
    && uv pip install --python /opt/canary/bin/python -r locked.txt . \
    && /opt/canary/bin/python -m playwright install --with-deps chromium \
    && test -f /opt/canary/lib/python3.14t/site-packages/starpulse/static/index.html
COPY ci/canary_smoke.py ci/fresh_serve.py /opt/canary/ci/
WORKDIR /opt/canary/ci
ENTRYPOINT ["python", "canary_smoke.py"]
