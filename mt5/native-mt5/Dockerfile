FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    DISPLAY=:1

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11vnc fluxbox novnc websockify \
    ca-certificates curl wget \
    libgtk-3-0 libasound2 libnss3 libxss1 libxtst6 libxkbcommon-x11-0 \
    libdbus-1-3 libxcomposite1 libglu1-mesa libxrandr2 libxi6 \
    fonts-dejavu tzdata && \
    rm -rf /var/lib/apt/lists/*

# Buat user non-root untuk menjalankan MT5
RUN useradd -ms /bin/bash mt5
USER root
WORKDIR /root

# Salin paket MT5 Linux (.deb) ke image saat build
# NOTE: Letakkan file 'mt5-linux.deb' di folder build ini sebelum build
COPY mt5-linux.deb /tmp/mt5-linux.deb

# Install MT5 Linux dan dependency yang dibutuhkan
RUN set -eux; \
    apt-get update; \
    apt-get install -y /tmp/mt5-linux.deb || true; \
    apt-get -f install -y; \
    rm -f /tmp/mt5-linux.deb; \
    rm -rf /var/lib/apt/lists/*

# Start script (Xvfb + fluxbox + x11vnc + noVNC + jalankan MT5)
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

USER mt5
WORKDIR /home/mt5

EXPOSE 17081 5901

CMD ["/usr/local/bin/start.sh"]
