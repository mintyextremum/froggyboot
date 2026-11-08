# Froggyboot test stand: server + a virtual PC in one container.
# QEMU's user-mode network gives the VM DHCP and TFTP itself, and the VM reaches
# nginx at 10.0.2.2, so no bridge, no root and no real network are touched.
FROM debian:trixie-slim AS ipxe
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      git ca-certificates make gcc libc6-dev binutils perl liblzma-dev mtools >/dev/null
RUN git clone -q --depth 1 https://github.com/ipxe/ipxe.git /ipxe
COPY server/embed.ipxe /embed.ipxe
RUN sed -i 's|@SERVER_IP@|10.0.2.2|' /embed.ipxe \
 && printf '#define REBOOT_CMD\n#define POWEROFF_CMD\n' > /ipxe/src/config/local/general.h \
 && printf '#define CONSOLE_SERIAL\n' > /ipxe/src/config/local/console.h \
 && make -C /ipxe/src -j"$(nproc)" bin/undionly.kpxe EMBED=/embed.ipxe 2>&1 | tail -40; test -f /ipxe/src/bin/undionly.kpxe

FROM debian:trixie-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      nginx apache2-utils python3 python3-fastapi python3-uvicorn python3-jinja2 python3-yaml \
      python3-passlib qemu-system-x86 sqlite3 procps curl >/dev/null && rm -rf /var/lib/apt/lists/*
COPY froggyboot /opt/froggyboot/froggyboot
COPY etc /opt/froggyboot/etc
COPY server /opt/froggyboot/server
COPY test/stand/stand.sh /stand.sh
COPY --from=ipxe /ipxe/src/bin/undionly.kpxe /srv/netboot/tftp/undionly.kpxe
ENV PYTHONPATH=/opt/froggyboot
EXPOSE 80
ENTRYPOINT ["bash", "/stand.sh"]
CMD ["check"]
