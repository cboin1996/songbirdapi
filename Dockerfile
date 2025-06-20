# TODO: add dockerfile once built.
ARG UBUNTU_VERSION="24.04"
FROM ubuntu:${UBUNTU_VERSION} AS builder

WORKDIR /songbirdapi

# make sure we use the venv
ENV PATH="/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc git python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# setup venv
RUN python3 -m venv /venv

COPY songbirdapi/requirements.txt .

# install dependencies
RUN pip install --no-cache-dir -r requirements.txt

FROM ubuntu:${UBUNTU_VERSION} AS build-image

ENV PATH="/venv/bin:$PATH"

WORKDIR /songbirdapi
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg python3-pip && \
    # clear cache
    rm -rf /var/lib/apt/lists/*

# copy venv
COPY --from=builder /venv /venv
# copy app contents
COPY ./songbirdapi/ ./songbirdapi
COPY pyproject.toml .

# install deps locally
RUN pip --no-cache-dir install .

EXPOSE 8000
ENTRYPOINT ["uvicorn", "songbirdapi.server:app", "--host", "0.0.0.0"]

# RUN tests to confirm built code runs as expected
# FROM build-image AS test
#
# RUN pip install -e .[dev]
# COPY tests ./tests
# WORKDIR /songbirdapi
# RUN python3 -m pytest ./tests/unit/
