FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g beads-ui @beads/bd

WORKDIR /workspace
