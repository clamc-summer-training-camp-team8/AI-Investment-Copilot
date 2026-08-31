#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 或 sudo 执行本脚本。" >&2
  exit 2
fi

deploy_user="${DEPLOY_USER:-root}"
if ! id "$deploy_user" >/dev/null 2>&1; then
  echo "部署用户不存在: $deploy_user" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --yes --no-install-recommends ca-certificates curl gnupg python3

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable
EOF

apt-get update
apt-get install --yes --no-install-recommends \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if [[ ! -s /etc/docker/daemon.json ]]; then
  install -m 0644 /dev/stdin /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "20m",
    "max-file": "5"
  },
  "live-restore": true
}
JSON
else
  echo "保留已有 /etc/docker/daemon.json；请人工确认日志轮转与 live-restore。"
fi

systemctl enable --now docker
systemctl restart docker

if [[ "$deploy_user" != "root" ]]; then
  usermod -aG docker "$deploy_user"
fi

# 2C4G 集成机只把 swap 当作突发保护，不能替代扩容。
if ! swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
  if [[ ! -e /swapfile ]]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=progress
  fi
  chmod 0600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
fi
if ! grep -Eq '^/swapfile[[:space:]]' /etc/fstab; then
  printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
fi
install -m 0644 /dev/stdin /etc/sysctl.d/99-ai-investment-copilot.conf <<'SYSCTL'
vm.swappiness=10
SYSCTL
sysctl --system >/dev/null

install -d -m 0750 -o "$deploy_user" -g "$deploy_user" \
  /opt/ai-investment-copilot \
  /opt/ai-investment-copilot/deploy \
  /opt/ai-investment-copilot/deploy/integration \
  /opt/ai-investment-copilot/backups
printf 'bootstrap-v1 %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > /opt/ai-investment-copilot/.bootstrap-v1
chown "$deploy_user:$deploy_user" /opt/ai-investment-copilot/.bootstrap-v1
chmod 0644 /opt/ai-investment-copilot/.bootstrap-v1

docker version --format 'Docker server {{.Server.Version}}'
docker compose version
echo "Alibaba Cloud Ubuntu integration host bootstrap complete"
