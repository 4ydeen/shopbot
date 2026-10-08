#!/bin/bash
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# اسکریپت نصب/آپدیت خودکار بات فروش کانفیگ V2Ray
#
# استفاده (بعد از اینکه این فایل را در مخزن گیت‌هاب خودت گذاشتی و REPO_URL را
# با آدرس ریپازیتوری خودت جایگزین کردی):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/USERNAME/v2ray-bot/main/install.sh)
#
# این اسکریپت هم برای نصب اولیه کار می‌کند و هم برای آپدیت‌های بعدی (idempotent است).

set -e

# جلوگیری از گیر کردن apt پشت پنجره‌های تعاملی (مثل پرسش needrestart برای ری‌استارت سرویس‌ها)
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export NEEDRESTART_SUSPEND=1


# ----------------------------------------------------------------------------
# رابط پیشرفت زنده: مراحل، درصد، زمان سپری‌شده و پیام‌های دوستانه
# ----------------------------------------------------------------------------
JOKES_FA=(
  "اوه اوه، پردازنده رو دارم می‌خورم 😅"
  "یک لحظه... دارم با سرور گپ می‌زنم ☕"
  "نگران نباش؛ هنوز هنگ نکردیم، داریم کار می‌کنیم 👀"
  "پکیج‌ها دارن صف می‌کشن 🚪"
  "اینترنت گفت صبر کن؛ منم دارم صبر می‌کنم 😂"
  "دارم پیچ و مهره‌های سرور رو سفت می‌کنم 🔧"
)
JOKES_EN=(
  "Oh oh, I'm eating the CPU 😅"
  "One moment... I'm chatting with the server ☕"
  "Don't worry; I'm not frozen, I'm working 👀"
  "Packages are lining up at the door 🚪"
  "The internet said wait, so I'm waiting 😂"
  "Tightening the server's nuts and bolts 🔧"
)

progress_bar() {
  local pct="$1" width=28 filled empty
  filled=$(( pct * width / 100 )); empty=$(( width - filled ))
  printf '['
  printf '%*s' "$filled" '' | tr ' ' '#'
  printf '%*s' "$empty" '' | tr ' ' '-'
  printf '] %3d%%' "$pct"
}

run_stage() {
  local idx="$1" total="$2" label="$3"; shift 3
  local log pid start now elapsed joke_count=0 joke pct status
  log="$(mktemp)"
  start=$(date +%s)
  "$@" >"$log" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    now=$(date +%s); elapsed=$((now-start))
    pct=$(( (idx-1) * 100 / total ))
    if [ "${SHOPVPN_UI_LANG:-fa}" = "fa" ]; then
      joke="${JOKES_FA[$((joke_count % ${#JOKES_FA[@]}))]}"
    else
      joke="${JOKES_EN[$((joke_count % ${#JOKES_EN[@]}))]}"
    fi
    printf '\r\033[K  '; progress_bar "$pct"
    printf '  %s · %02ds · %s' "$label" "$elapsed" "$joke"
    joke_count=$((joke_count+1)); sleep 2
  done
  wait "$pid"; status=$?
  elapsed=$(( $(date +%s)-start ))
  printf '\r\033[K  '; progress_bar "$((idx*100/total))"
  if [ "$status" -eq 0 ]; then
    printf '  ✓ %s · %02ds\n' "$label" "$elapsed"
  else
    printf '  ✗ %s · %02ds\n' "$label" "$elapsed"
    tail -8 "$log" | sed 's/^/      /'
  fi
  rm -f "$log"
  return "$status"
}

# ============================================================================
# تنظیمات - این خط را با آدرس مخزن گیت‌هاب خودت جایگزین کن
# ============================================================================
REPO_URL="https://github.com/mehdirafatpanah/Shopvpn.git"
INSTALL_DIR="$HOME/v2ray_bot"
SERVICE_NAME="v2raybot"

echo "🚀 شروع نصب/آپدیت بات فروش کانفیگ V2Ray"
echo "──────────────────────────────────────────"
echo "نمایش پیشرفت زنده فعال است؛ اگر یک مرحله طول کشید، ترمینال هنگ نکرده است."
echo ""

TOTAL_STEPS=6

# ۱. پیش‌نیازها
run_stage 1 "$TOTAL_STEPS" "📦 نصب پیش‌نیازهای سیستم" bash -c   "sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get update -qq && timeout 120 sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 apt-get install -y -qq git python3 python3-pip python3-venv ca-certificates curl >/dev/null"

# ----------------------------------------------------------------------------
# ۲. دریافت یا آپدیت کد از گیت‌هاب
#    نکته: بعضی سرورها (خصوصاً VPSهای ارزان) با پروتکل git-over-https توسط
#    گیت‌هاب مسدود/محدود می‌شوند و به‌جای کلون عادی، درخواست یوزرنیم/پسورد
#    نشان داده می‌شود. برای جلوگیری از گیر کردن اسکریپت روی این پرامپت،
#    اول با گیت (بدون امکان پرامپت تعاملی) تلاش می‌کنیم و در صورت شکست،
#    به دانلود مستقیم آرشیو (tar.gz) که این محدودیت را ندارد سوییچ می‌کنیم.
# ----------------------------------------------------------------------------
GITHUB_OWNER="mehdirafatpanah"
GITHUB_REPO="Shopvpn"
GITHUB_BRANCH="main"
export GIT_TERMINAL_PROMPT=0

#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
fetch_project_code() {
    local ok=0
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo "🔄 مخزن از قبل موجود است، در حال دریافت آخرین تغییرات..."
        if git -C "$INSTALL_DIR" pull --quiet; then ok=1; fi
    else
        echo "📥 دریافت پروژه از گیت‌هاب..."
        if git clone --quiet "$REPO_URL" "$INSTALL_DIR"; then ok=1; fi
    fi

    if [ "$ok" = "1" ]; then
        return 0
    fi

    echo "⚠️ دسترسی git مسدود شد، در حال دریافت از طریق آرشیو مستقیم..."
    local tmp_tar tmp_dir
    tmp_tar=$(mktemp)
    tmp_dir=$(mktemp -d)
    if ! curl -fsSL "https://codeload.github.com/${GITHUB_OWNER}/${GITHUB_REPO}/tar.gz/refs/heads/${GITHUB_BRANCH}" -o "$tmp_tar"; then
        echo "❌ دانلود آرشیو پروژه هم ناموفق بود. اتصال اینترنت سرور را بررسی کن."
        rm -f "$tmp_tar"; rm -rf "$tmp_dir"
        return 1
    fi
    tar -xzf "$tmp_tar" -C "$tmp_dir" --strip-components=1
    rm -f "$tmp_tar"
    mkdir -p "$INSTALL_DIR"
    if ! command -v rsync > /dev/null 2>&1; then
        sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync > /dev/null
    fi
    rsync -a --exclude='.env' --exclude='*.db' --exclude='*.db-journal' \
        --exclude='*.sqlite3' --exclude='venv' --exclude='.git' --exclude='backups' \
        "$tmp_dir"/ "$INSTALL_DIR"/
    rm -rf "$INSTALL_DIR/.git" 2>/dev/null
    rm -rf "$tmp_dir"
    return 0
}

run_stage 2 "$TOTAL_STEPS" "📥 دریافت/آپدیت پروژه از GitHub" fetch_project_code
cd "$INSTALL_DIR"

# ----------------------------------------------------------------------------
# ۳. ساخت virtual environment و نصب پکیج‌ها
# ----------------------------------------------------------------------------
run_stage 3 "$TOTAL_STEPS" "🐍 آماده‌سازی Python و نصب پکیج‌ها" bash -c '
    if [ ! -d "venv" ]; then python3 -m venv venv; fi
    source venv/bin/activate
    pip install -r requirements.txt --quiet
    deactivate
'

# ----------------------------------------------------------------------------
# ۴. تنظیم فایل .env (فقط دفعه اول، چون این فایل هیچ‌وقت در گیت نیست)
# ----------------------------------------------------------------------------
echo ""
echo "  [مرحله ۴/$TOTAL_STEPS] 🔑 تنظیم اطلاعات بات"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo ""
    echo "🔑 فایل .env پیدا نشد. اطلاعات زیر را وارد کن:"
    read -rp "توکن بات (از BotFather): " BOT_TOKEN_INPUT
    read -rp "آیدی عددی ادمین (مثلاً از @userinfobot): " OWNER_ID_INPUT
    cat > "$INSTALL_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN_INPUT
OWNER_ID=$OWNER_ID_INPUT
EOF

    echo ""
    echo "بات چطور آپدیت‌های تلگرام را دریافت کند؟"
    echo "  1) Polling  (پیش‌فرض - ساده‌تر، نیاز به دامنه/SSL ندارد)"
    echo "  2) Webhook  (نیاز به یک دامنه که DNS آن روی IP همین سرور تنظیم شده)"
    read -rp "انتخاب [1]: " BOT_MODE_CHOICE
    BOT_MODE_CHOICE="${BOT_MODE_CHOICE:-1}"

    if [ "$BOT_MODE_CHOICE" = "2" ]; then
        read -rp "دامنه‌ای که برای وب‌هوک بات استفاده می‌کنی (مثلاً bot.example.com): " WEBHOOK_DOMAIN
        if [ -z "$WEBHOOK_DOMAIN" ]; then
            echo "⚠️ دامنه وارد نشد؛ بات با Polling راه‌اندازی می‌شود (بعداً از منوی manage.sh می‌توانی وب‌هوک را فعال کنی)."
        else
            WEBHOOK_PORT=8010
            echo "📦 نصب nginx و certbot..."
            sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1 \
                apt-get install -y -qq nginx certbot python3-certbot-nginx > /dev/null

            echo "🌐 تنظیم nginx برای $WEBHOOK_DOMAIN..."
            sudo bash -c "cat > /etc/nginx/sites-available/${WEBHOOK_DOMAIN}.conf" <<NGXEOF
server {
    listen 80;
    server_name $WEBHOOK_DOMAIN;
    client_max_body_size 100m;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;

    location / {
        proxy_pass http://127.0.0.1:$WEBHOOK_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGXEOF
            sudo ln -sf "/etc/nginx/sites-available/${WEBHOOK_DOMAIN}.conf" "/etc/nginx/sites-enabled/${WEBHOOK_DOMAIN}.conf"

            if ! sudo nginx -t > /dev/null 2>&1; then
                echo "⛔️ کانفیگ nginx خطا دارد؛ بات با Polling راه‌اندازی می‌شود."
            else
                sudo systemctl reload nginx
                echo "🔐 دریافت گواهی SSL (Let's Encrypt)..."
                if sudo certbot --nginx -d "$WEBHOOK_DOMAIN" --non-interactive --agree-tos \
                    --register-unsafely-without-email --redirect; then
                    WEBHOOK_SECRET_VAL=$(python3 -c "import secrets; print(secrets.token_hex(24))")
                    cat >> "$INSTALL_DIR/.env" <<EOF
BOT_MODE=webhook
WEBHOOK_BASE_URL=https://$WEBHOOK_DOMAIN
WEBHOOK_SECRET=$WEBHOOK_SECRET_VAL
WEBHOOK_LISTEN_HOST=127.0.0.1
WEBHOOK_LISTEN_PORT=$WEBHOOK_PORT
EOF
                    echo "✅ حالت Webhook تنظیم شد: https://$WEBHOOK_DOMAIN"
                else
                    echo "⛔️ دریافت SSL ناموفق بود؛ بات با Polling راه‌اندازی می‌شود (بعداً از منوی manage.sh دوباره امتحان کن)."
                fi
            fi
        fi
    fi
    echo "✅ فایل .env ساخته شد."
else
    echo "✅ فایل .env از قبل موجود است، دست‌نخورده باقی می‌ماند."
fi

# ----------------------------------------------------------------------------
# ۵. نصب و راه‌اندازی خودکار موتور ترجمه محلی
#    کاربر نباید هیچ مدل Argos یا LibreTranslate را دستی نصب کند.
# ----------------------------------------------------------------------------
bash "$INSTALL_DIR/setup_local_translation.sh" --ask || true
run_stage 5 "$TOTAL_STEPS" "🌍 نصب موتور ترجمه و مدل‌های زبان" bash -c "bash '$INSTALL_DIR/setup_local_translation.sh'" ||     echo "⚠️ نصب موتور ترجمه کامل نشد؛ بات ادامه می‌دهد و در آپدیت بعدی دوباره تلاش می‌کند."

# ۶. ساخت و راه‌اندازی systemd
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
run_stage 6 "$TOTAL_STEPS" "⚙️ ساخت و راه‌اندازی سرویس دائمی" bash -c "
sudo bash -c 'cat > "$SERVICE_FILE"' <<EOF
[Unit]
Description=V2Ray Telegram Sales Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/main.py
Restart=always
RestartSec=5
User=$(whoami)

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable '$SERVICE_NAME' >/dev/null 2>&1
sudo systemctl restart '$SERVICE_NAME'
sleep 2
"

echo ""
echo "──────────────────────────────────────────"
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ بات با موفقیت نصب/آپدیت شد و در حال اجراست."
else
    echo "⚠️ بات اجرا نشد. برای دیدن جزئیات خطا:"
    echo "   sudo journalctl -u $SERVICE_NAME -n 50 --no-pager"
fi
echo ""
echo "دستورات مفید:"
echo "  وضعیت بات:    sudo systemctl status $SERVICE_NAME"
echo "  لاگ زنده:      sudo journalctl -u $SERVICE_NAME -f"
echo "  ری‌استارت:     sudo systemctl restart $SERVICE_NAME"
echo "  متوقف کردن:    sudo systemctl stop $SERVICE_NAME"
echo "──────────────────────────────────────────"
#‍​‌‌​​​‌‌​‌‌​​‌​‌​‌‌​‌‌​​​‌‌​​‌​‌​‌‌​‌‌‌​​‌‌​‌‌‌‌​‌‌‌​​‌​‍
# 		   		 		  	 	 		 		   		  	 	 		 			  		 				 			  	 
