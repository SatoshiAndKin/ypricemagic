# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends build-essential git libgmp-dev curl ca-certificates
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup.sh && \
    sh /tmp/rustup.sh -y --profile minimal --default-toolchain 1.98.1 --no-modify-path
ENV PATH="/root/.cargo/bin:${PATH}" CARGO_BUILD_JOBS=4
WORKDIR /opt/validation
COPY requirements.txt requirements-dev.txt requirements-build.txt constraints.txt cache-build-dependencies.lock ./
# Pass the backend pin into pip's isolated source builds too.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cargo/registry,sharing=locked \
    PIP_CONSTRAINT=/opt/validation/cache-build-dependencies.lock \
    python -m pip install -c constraints.txt -r requirements-build.txt -r requirements-dev.txt && \
    python -m pip freeze --all > dependencies.txt && python -m pip check
WORKDIR /work
