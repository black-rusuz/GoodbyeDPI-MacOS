FROM debian:bookworm-slim

# Установка системных зависимостей, curl, python3 и компилятора C
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    python3 \
    ca-certificates \
    iproute2 \
    gcc \
    make \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
