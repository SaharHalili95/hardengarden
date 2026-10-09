# Disposable test system for remediation templates (Phase 3). Mirrors the misconfigured
# fixture scenario. Never used for anything but CI tests; nothing here ships.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server sudo passwd iproute2 procps iptables kmod ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# --- misconfiguration -------------------------------------------------------------
RUN printf 'PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n' \
        > /etc/ssh/sshd_config.d/50-insecure.conf \
 && useradd -m -s /bin/bash alice \
 && echo 'alice:Correct-Horse-Battery-9' | chpasswd \
 && install -d -m 0700 -o alice -g alice /home/alice/.ssh \
 && printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC0hardengarden0test0key0not0a0real0key00000000 test\n' \
        > /home/alice/.ssh/authorized_keys \
 && chown alice:alice /home/alice/.ssh/authorized_keys && chmod 0600 /home/alice/.ssh/authorized_keys \
 && useradd -o -u 0 -g 0 -M -d /root -s /bin/bash toor \
 && printf 'alice ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/90-ops && chmod 0440 /etc/sudoers.d/90-ops \
 && chmod 0644 /etc/shadow && chmod 0666 /etc/passwd \
 && mkdir -p /etc/app /etc/cron.d && touch /etc/cron.d/backup \
 && chmod 0666 /etc/cron.d/backup && chmod 0777 /etc/app \
 && printf 'kernel.randomize_va_space = 0\n' > /etc/sysctl.d/10-insecure.conf \
 && mkdir -p /run/sshd
CMD ["sleep", "infinity"]
