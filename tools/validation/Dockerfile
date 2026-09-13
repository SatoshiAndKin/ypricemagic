# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends build-essential git libgmp-dev
WORKDIR /opt/validation
COPY requirements.txt requirements-dev.txt requirements-build.txt constraints.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -c constraints.txt -r requirements-build.txt -r requirements-dev.txt && \
    python -m pip freeze --all > dependencies.txt && python -m pip check
WORKDIR /work
