FROM telegraf:1.32-alpine

USER root

# python3 + cryptography deps from alpine repos (avoids building from source).
# py3-paramiko + py3-cryptography satisfy netmiko's heaviest transitive deps.
RUN apk add --no-cache \
        python3 \
        py3-pip \
        py3-requests \
        py3-cryptography \
        py3-paramiko \
        py3-yaml \
    && pip3 install --no-cache-dir --break-system-packages --no-deps \
        ucsmsdk \
    && pip3 install --no-cache-dir --break-system-packages \
        netmiko

USER telegraf
