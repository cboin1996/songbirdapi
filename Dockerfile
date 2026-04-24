ARG UBUNTU_VERSION="24.04"
FROM ubuntu:${UBUNTU_VERSION} AS builder

WORKDIR /songbirdapi

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc git python3 && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY ./songbirdapi/ ./songbirdapi

RUN uv sync --frozen --no-dev

FROM ubuntu:${UBUNTU_VERSION} AS build-image

WORKDIR /songbirdapi

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg python3 curl unzip && \
    ARCH=$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/aarch64/') && \
    curl -fsSL "https://github.com/denoland/deno/releases/latest/download/deno-${ARCH}-unknown-linux-gnu.zip" -o /tmp/deno.zip && \
    unzip /tmp/deno.zip -d /usr/local/bin && \
    rm /tmp/deno.zip && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /songbirdapi/.venv /songbirdapi/.venv
COPY ./songbirdapi/ ./songbirdapi
COPY pyproject.toml uv.lock ./

ENV PATH="/songbirdapi/.venv/bin:$PATH"

RUN deno --help

EXPOSE 8000
ENTRYPOINT ["uvicorn", "songbirdapi.server:app", "--host", "0.0.0.0"]
