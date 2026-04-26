FROM telegraf:1.32-alpine

USER root

# python3 + cryptography deps from alpine repos (avoids building from source).
# py3-paramiko + py3-cryptography satisfy netmiko's heaviest transitive deps.
# py3-six is required by ucsmsdk's ucsgenutils.
RUN apk add --no-cache \
        python3 \
        py3-pip \
        py3-requests \
        py3-cryptography \
        py3-paramiko \
        py3-yaml \
        py3-six \
    && pip3 install --no-cache-dir --break-system-packages \
        ucsmsdk \
        netmiko

# The script writes its log at /var/log/telegraf/<script-name>/<...>.log
# Pre-create the directory so the script's setup_logging() succeeds on
# first run instead of falling back to /utm (which is read-only for the
# telegraf user via bind mount).
RUN mkdir -p /var/log/telegraf/ucs_traffic_monitor \
    && chown -R telegraf:telegraf /var/log/telegraf

USER telegraf
