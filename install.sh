#!/bin/bash

# ============================================================
# StormDNS Panel - اسکریپت نصب خودکار
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PANEL_DIR="/root/stormdns_panel"
SERVICE_NAME="stormdns-panel"
PANEL_PORT="8888"
GITHUB_RAW="https://raw.githubusercontent.com/booklistner/stormdns-panel/main"

print_banner() {
  echo -e "${CYAN}"
  echo "  ╔═══════════════════════════════════════╗"
  echo "  ║         StormDNS Panel Installer      ║"
  echo "  ║              v1.0.0                   ║"
  echo "  ╚═══════════════════════════════════════╝"
  echo -e "${NC}"
}

print_step() { echo -e "${BLUE}[*]${NC} $1"; }
print_ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
print_err()  { echo -e "${RED}[✗]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }

check_root() {
  if [ "$EUID" -ne 0 ]; then
    print_err "این اسکریپت باید با root اجرا شود"
    exit 1
  fi
}

install_dependencies() {
  print_step "نصب وابستگی‌ها..."
  apt update -qq
  apt install -y python3 python3-pip python3-venv vnstat curl wget -qq
  print_ok "وابستگی‌ها نصب شدند"
}

setup_panel() {
  print_step "دانلود فایل‌های پنل..."
  mkdir -p "$PANEL_DIR/templates"

  wget -q "$GITHUB_RAW/app.py" -O "$PANEL_DIR/app.py"
  wget -q "$GITHUB_RAW/templates/login.html" -O "$PANEL_DIR/templates/login.html"
  wget -q "$GITHUB_RAW/templates/dashboard.html" -O "$PANEL_DIR/templates/dashboard.html"

  print_ok "فایل‌ها دانلود شدند"
}

setup_venv() {
  print_step "ساخت محیط Python..."
  python3 -m venv "$PANEL_DIR/venv"
  "$PANEL_DIR/venv/bin/pip" install flask qrcode pillow psutil -q
  print_ok "محیط Python آماده شد"
}

set_admin_password() {
  echo ""
  echo -e "${YELLOW}پسورد ادمین پنل را انتخاب کنید:${NC}"
  read -s -p "پسورد: " ADMIN_PASS
  echo ""
  read -s -p "تکرار پسورد: " ADMIN_PASS2
  echo ""

  if [ "$ADMIN_PASS" != "$ADMIN_PASS2" ]; then
    print_err "پسوردها یکسان نیستند"
    exit 1
  fi

  sed -i "s/ADMIN_PASSWORD = 'admin123'/ADMIN_PASSWORD = '$ADMIN_PASS'/" "$PANEL_DIR/app.py"
  print_ok "پسورد تنظیم شد"
}

set_port() {
  echo ""
  echo -e "${YELLOW}پورت پنل را وارد کنید (پیش‌فرض: 8888):${NC}"
  read -p "پورت: " INPUT_PORT
  if [ ! -z "$INPUT_PORT" ]; then
    PANEL_PORT=$INPUT_PORT
    sed -i "s/port=8888/port=$PANEL_PORT/" "$PANEL_DIR/app.py"
  fi
  ufw allow "$PANEL_PORT/tcp" > /dev/null 2>&1
  print_ok "پورت $PANEL_PORT تنظیم شد"
}

create_service() {
  print_step "ساخت سرویس systemd..."
  cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=StormDNS Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$PANEL_DIR
ExecStart=$PANEL_DIR/venv/bin/python $PANEL_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME" > /dev/null 2>&1
  systemctl start "$SERVICE_NAME"
  print_ok "سرویس ساخته و اجرا شد"
}

setup_vnstat() {
  print_step "راه‌اندازی vnstat..."
  vnstat --add -i eth0 > /dev/null 2>&1
  systemctl enable vnstat > /dev/null 2>&1
  systemctl start vnstat > /dev/null 2>&1
  print_ok "vnstat آماده شد"
}

print_result() {
  SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "IP_SERVER")
  echo ""
  echo -e "${GREEN}╔═══════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║       نصب با موفقیت انجام شد!        ║${NC}"
  echo -e "${GREEN}╚═══════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  آدرس پنل: ${CYAN}http://$SERVER_IP:$PANEL_PORT${NC}"
  echo ""
  echo -e "  دستورات مفید:"
  echo -e "  ${YELLOW}systemctl status $SERVICE_NAME${NC}   وضعیت پنل"
  echo -e "  ${YELLOW}systemctl restart $SERVICE_NAME${NC}  ری‌استارت پنل"
  echo -e "  ${YELLOW}systemctl stop $SERVICE_NAME${NC}     توقف پنل"
  echo ""
}

uninstall() {
  print_warn "در حال حذف StormDNS Panel..."
  systemctl stop "$SERVICE_NAME" > /dev/null 2>&1
  systemctl disable "$SERVICE_NAME" > /dev/null 2>&1
  rm -f "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  rm -rf "$PANEL_DIR"
  print_ok "پنل حذف شد"
  exit 0
}

# Main
print_banner
check_root

if [ "$1" == "--uninstall" ]; then
  uninstall
fi

install_dependencies
setup_panel
setup_venv
set_admin_password
set_port
setup_vnstat
create_service
print_result
