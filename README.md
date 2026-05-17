# ⚡ StormDNS Panel

پنل مدیریت ساده برای سرور StormDNS

## امکانات

- ➕ افزودن و مدیریت کاربران
- 📅 تنظیم تاریخ انقضا
- 📊 محدودیت حجم مصرف
- 📱 QR Code برای اتصال سریع
- ⚙️ مشاهده کانفیگ اتصال
- 🔄 ری‌استارت سرور از پنل
- 📈 آمار مصرف کل سرور

## نصب سریع

```bash
bash <(curl -Ls https://raw.githubusercontent.com/booklistner/stormdns-panel/main/install.sh)
```

## حذف

```bash
bash <(curl -Ls https://raw.githubusercontent.com/booklistner/stormdns-panel/main/install.sh) --uninstall
```

## پیش‌نیاز

- سرور لینوکس Ubuntu 22.04 / Debian 12
- StormDNS نصب شده روی سرور
- Python 3.10+

## دستورات مفید

```bash
# وضعیت پنل
systemctl status stormdns-panel

# ری‌استارت
systemctl restart stormdns-panel

# لاگ‌ها
journalctl -u stormdns-panel -f
```

## توجه

این پنل برای مدیریت سرور StormDNS طراحی شده و نیاز به نصب قبلی StormDNS دارد.
