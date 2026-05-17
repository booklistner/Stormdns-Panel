from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
import json, os, subprocess, io, hashlib, secrets, time, re
from datetime import datetime, timedelta
from functools import wraps
import qrcode
import psutil

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ============================================================
# Config
# ============================================================
PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(PANEL_DIR, 'users.json')
CONFIG_FILE = os.path.join(PANEL_DIR, 'panel_config.json')
ENCRYPT_KEY_FILE = '/root/encrypt_key.txt'
SERVER_CONFIG_FILE = '/root/server_config.toml'

# Rate limiting storage
login_attempts = {}
blocked_ips = {}

# ============================================================
# Security helpers
# ============================================================
def hash_password(password):
    salt = 'stormdns_salt_2026'
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def get_client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

def is_blocked(ip):
    if ip in blocked_ips:
        if time.time() < blocked_ips[ip]:
            return True
        else:
            del blocked_ips[ip]
    return False

def record_failed_login(ip):
    now = time.time()
    if ip not in login_attempts:
        login_attempts[ip] = []
    login_attempts[ip] = [t for t in login_attempts[ip] if now - t < 300]
    login_attempts[ip].append(now)
    if len(login_attempts[ip]) >= 5:
        blocked_ips[ip] = now + 1800  # block 30 min
        login_attempts[ip] = []
        return True
    return False

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            if request.is_json:
                return jsonify({'error': 'unauthorized'}), 401
            return redirect(url_for('login'))
        # Session timeout: 8 hours
        if time.time() - session.get('login_time', 0) > 28800:
            session.clear()
            if request.is_json:
                return jsonify({'error': 'session expired'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def sanitize(s, max_len=64):
    if not s:
        return ''
    s = str(s).strip()[:max_len]
    return re.sub(r'[^\w\-. @]', '', s)

# ============================================================
# Panel config
# ============================================================
DEFAULT_CONFIG = {
    'admin_password': hash_password('admin123'),
    'panel_port': 8888,
    'server_domain': 'v.mohadese.shop',
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            c = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in c:
                    c[k] = v
            return c
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# ============================================================
# Users
# ============================================================
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def check_expired_users():
    users = load_users()
    changed = False
    for u, data in users.items():
        if data.get('active') and data.get('expire_date'):
            expire = datetime.strptime(data['expire_date'], '%Y-%m-%d')
            if datetime.now() > expire:
                users[u]['active'] = False
                changed = True
    if changed:
        save_users(users)

# ============================================================
# Server config helpers
# ============================================================
def get_encrypt_key():
    try:
        with open(ENCRYPT_KEY_FILE, 'r') as f:
            return f.read().strip()
    except:
        return 'KEY_NOT_FOUND'

def get_server_config():
    config = {}
    try:
        with open(SERVER_CONFIG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                config[key.strip()] = value.strip()
    except:
        pass
    return config

def save_server_config_value(key, value):
    try:
        with open(SERVER_CONFIG_FILE, 'r') as f:
            content = f.read()
        pattern = rf'^({re.escape(key)}\s*=\s*)(.+)$'
        new_content = re.sub(pattern, rf'\g<1>{value}', content, flags=re.MULTILINE)
        with open(SERVER_CONFIG_FILE, 'w') as f:
            f.write(new_content)
        return True
    except:
        return False

# ============================================================
# System stats
# ============================================================
def get_system_stats():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    net_before = psutil.net_io_counters()
    time.sleep(0.5)
    net_after = psutil.net_io_counters()
    
    net_in  = round((net_after.bytes_recv - net_before.bytes_recv) * 2 / 1024, 1)
    net_out = round((net_after.bytes_sent - net_before.bytes_sent) * 2 / 1024, 1)

    return {
        'cpu': cpu,
        'mem_percent': mem.percent,
        'mem_used': round(mem.used / 1024**3, 2),
        'mem_total': round(mem.total / 1024**3, 2),
        'disk_percent': disk.percent,
        'disk_used': round(disk.used / 1024**3, 1),
        'disk_total': round(disk.total / 1024**3, 1),
        'net_in_kb': net_in,
        'net_out_kb': net_out,
        'uptime': get_uptime(),
    }

def get_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            seconds = float(f.readline().split()[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    except:
        return 'N/A'

def get_traffic_stats():
    try:
        result = subprocess.run(['vnstat', '--json', '-i', 'eth0'],
                                capture_output=True, text=True, timeout=5)
        data = json.loads(result.stdout)
        interfaces = data.get('interfaces', [])
        if interfaces:
            traffic = interfaces[0].get('traffic', {})
            total = traffic.get('total', {})
            rx = total.get('rx', 0)
            tx = total.get('tx', 0)
            return {
                'rx_gb': round(rx / 1024**3, 2),
                'tx_gb': round(tx / 1024**3, 2),
                'total_gb': round((rx + tx) / 1024**3, 2),
            }
    except:
        pass
    return {'rx_gb': 0, 'tx_gb': 0, 'total_gb': 0}

# ============================================================
# Routes - Auth
# ============================================================
@app.before_request
def before_request():
    check_expired_users()
    # Security headers
    pass

@app.after_request
def after_request(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://fonts.googleapis.com https://fonts.gstatic.com"
    return response

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = get_client_ip()
    if is_blocked(ip):
        remaining = int((blocked_ips[ip] - time.time()) / 60)
        return render_template('login.html', error=f'IP شما به مدت {remaining} دقیقه مسدود شده است')

    if request.method == 'POST':
        password = request.form.get('password', '')
        config = load_config()
        if hash_password(password) == config['admin_password']:
            session['logged_in'] = True
            session['login_time'] = time.time()
            login_attempts.pop(ip, None)
            return redirect(url_for('dashboard'))
        else:
            blocked = record_failed_login(ip)
            attempts = len(login_attempts.get(ip, []))
            if blocked:
                return render_template('login.html', error='IP شما مسدود شد (۵ تلاش ناموفق)')
            return render_template('login.html', error=f'پسورد اشتباه است ({attempts}/5 تلاش)')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============================================================
# Routes - Dashboard
# ============================================================
@app.route('/dashboard')
@login_required
def dashboard():
    users = load_users()
    stats = get_traffic_stats()
    active_count = sum(1 for u in users.values() if u.get('active'))
    expired_count = sum(1 for u in users.values() if not u.get('active'))
    return render_template('dashboard.html',
                           users=users,
                           stats=stats,
                           active_count=active_count,
                           expired_count=expired_count,
                           total_count=len(users))

# ============================================================
# Routes - Users API
# ============================================================
@app.route('/api/add_user', methods=['POST'])
@login_required
def add_user():
    data = request.json or {}
    username = sanitize(data.get('username', ''), 32)
    days = max(1, min(int(data.get('days', 30)), 3650))
    volume_gb = max(0.1, min(float(data.get('volume_gb', 5)), 10000))
    note = sanitize(data.get('note', ''), 100)

    if not username:
        return jsonify({'error': 'نام کاربری خالی است'}), 400
    if not re.match(r'^[\w\-\.]+$', username):
        return jsonify({'error': 'نام کاربری فقط می‌تواند شامل حروف، اعداد و - باشد'}), 400

    users = load_users()
    if username in users:
        return jsonify({'error': 'این کاربر قبلاً وجود دارد'}), 400

    expire_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    users[username] = {
        'username': username,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'expire_date': expire_date,
        'days': days,
        'volume_gb': volume_gb,
        'used_gb': 0,
        'active': True,
        'note': note,
    }
    save_users(users)
    return jsonify({'success': True, 'message': f'کاربر {username} اضافه شد'})

@app.route('/api/delete_user/<username>', methods=['DELETE'])
@login_required
def delete_user(username):
    username = sanitize(username, 32)
    users = load_users()
    if username not in users:
        return jsonify({'error': 'کاربر پیدا نشد'}), 404
    del users[username]
    save_users(users)
    return jsonify({'success': True})

@app.route('/api/toggle_user/<username>', methods=['POST'])
@login_required
def toggle_user(username):
    username = sanitize(username, 32)
    users = load_users()
    if username not in users:
        return jsonify({'error': 'کاربر پیدا نشد'}), 404
    users[username]['active'] = not users[username]['active']
    save_users(users)
    return jsonify({'success': True, 'active': users[username]['active']})

@app.route('/api/extend_user/<username>', methods=['POST'])
@login_required
def extend_user(username):
    username = sanitize(username, 32)
    data = request.json or {}
    days = max(1, min(int(data.get('days', 30)), 3650))
    users = load_users()
    if username not in users:
        return jsonify({'error': 'کاربر پیدا نشد'}), 404
    current = datetime.strptime(users[username]['expire_date'], '%Y-%m-%d')
    if current < datetime.now():
        current = datetime.now()
    new_expire = current + timedelta(days=days)
    users[username]['expire_date'] = new_expire.strftime('%Y-%m-%d')
    users[username]['active'] = True
    save_users(users)
    return jsonify({'success': True, 'new_expire': users[username]['expire_date']})

@app.route('/api/qrcode/<username>')
@login_required
def get_qrcode(username):
    username = sanitize(username, 32)
    users = load_users()
    if username not in users:
        return jsonify({'error': 'کاربر پیدا نشد'}), 404
    config = load_config()
    encrypt_key = get_encrypt_key()
    domain = config.get('server_domain', 'v.mohadese.shop')
    config_text = f"DOMAINS={domain}\nENCRYPTION_KEY={encrypt_key}\nSERVER=stormdns\nUSER={username}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(config_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/api/config/<username>')
@login_required
def get_config_user(username):
    username = sanitize(username, 32)
    users = load_users()
    if username not in users:
        return jsonify({'error': 'کاربر پیدا نشد'}), 404
    config = load_config()
    encrypt_key = get_encrypt_key()
    domain = config.get('server_domain', 'v.mohadese.shop')
    cfg = f"""# StormDNS Config - {username}
DOMAINS = ["{domain}"]
DATA_ENCRYPTION_METHOD = 2
ENCRYPTION_KEY = "{encrypt_key}"
PROTOCOL_TYPE = "SOCKS5"
LISTEN_IP = "127.0.0.1"
LISTEN_PORT = 18000"""
    return jsonify({'config': cfg, 'domain': domain, 'key': encrypt_key})

# ============================================================
# Routes - System
# ============================================================
@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_system_stats())

@app.route('/api/traffic')
@login_required
def api_traffic():
    return jsonify(get_traffic_stats())

@app.route('/api/server_status')
@login_required
def server_status():
    try:
        result = subprocess.run(['systemctl', 'is-active', 'stormdns'],
                                capture_output=True, text=True, timeout=5)
        status = result.stdout.strip()
        return jsonify({'status': status, 'running': status == 'active'})
    except:
        return jsonify({'status': 'unknown', 'running': False})

@app.route('/api/restart_server', methods=['POST'])
@login_required
def restart_server():
    try:
        subprocess.run(['systemctl', 'restart', 'stormdns'], timeout=10)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================
# Routes - Server Config
# ============================================================
@app.route('/api/server_config', methods=['GET'])
@login_required
def get_server_config_api():
    raw = get_server_config()
    # Extract key values for UI
    result = {
        'DATA_ENCRYPTION_METHOD': raw.get('DATA_ENCRYPTION_METHOD', '2'),
        'UDP_READERS': raw.get('UDP_READERS', '7'),
        'DNS_REQUEST_WORKERS': raw.get('DNS_REQUEST_WORKERS', '7'),
        'MAX_CONCURRENT_REQUESTS': raw.get('MAX_CONCURRENT_REQUESTS', '16384'),
        'ARQ_INITIAL_RTO_SECONDS': raw.get('ARQ_INITIAL_RTO_SECONDS', '0.3'),
        'ARQ_MAX_RTO_SECONDS': raw.get('ARQ_MAX_RTO_SECONDS', '2.0'),
        'ARQ_CONTROL_INITIAL_RTO_SECONDS': raw.get('ARQ_CONTROL_INITIAL_RTO_SECONDS', '0.3'),
        'ARQ_CONTROL_MAX_RTO_SECONDS': raw.get('ARQ_CONTROL_MAX_RTO_SECONDS', '1.5'),
        'MAX_PACKETS_PER_BATCH': raw.get('MAX_PACKETS_PER_BATCH', '20'),
        'PACKET_BLOCK_CONTROL_DUPLICATION': raw.get('PACKET_BLOCK_CONTROL_DUPLICATION', '3'),
        'SOCKET_BUFFER_SIZE': raw.get('SOCKET_BUFFER_SIZE', '8388608'),
        'SESSION_TIMEOUT_SECONDS': raw.get('SESSION_TIMEOUT_SECONDS', '300.0'),
        'ARQ_WINDOW_SIZE': raw.get('ARQ_WINDOW_SIZE', '1000'),
        'DEFERRED_SESSION_WORKERS': raw.get('DEFERRED_SESSION_WORKERS', '4'),
        'LOG_LEVEL': raw.get('LOG_LEVEL', '"INFO"'),
    }
    return jsonify(result)

@app.route('/api/server_config', methods=['POST'])
@login_required
def update_server_config():
    data = request.json or {}
    allowed_keys = [
        'DATA_ENCRYPTION_METHOD', 'UDP_READERS', 'DNS_REQUEST_WORKERS',
        'MAX_CONCURRENT_REQUESTS', 'ARQ_INITIAL_RTO_SECONDS', 'ARQ_MAX_RTO_SECONDS',
        'ARQ_CONTROL_INITIAL_RTO_SECONDS', 'ARQ_CONTROL_MAX_RTO_SECONDS',
        'MAX_PACKETS_PER_BATCH', 'PACKET_BLOCK_CONTROL_DUPLICATION',
        'SOCKET_BUFFER_SIZE', 'SESSION_TIMEOUT_SECONDS', 'ARQ_WINDOW_SIZE',
        'DEFERRED_SESSION_WORKERS', 'LOG_LEVEL',
    ]
    errors = []
    for key in allowed_keys:
        if key in data:
            val = str(data[key]).strip()
            if not re.match(r'^[\w\.\-"]+$', val):
                errors.append(f'مقدار نامعتبر برای {key}')
                continue
            if not save_server_config_value(key, val):
                errors.append(f'خطا در ذخیره {key}')
    if errors:
        return jsonify({'error': ' | '.join(errors)}), 400
    return jsonify({'success': True, 'message': 'تنظیمات ذخیره شد'})

@app.route('/api/apply_optimized', methods=['POST'])
@login_required
def apply_optimized():
    optimized = {
        'DATA_ENCRYPTION_METHOD': '2',
        'UDP_READERS': '14',
        'DNS_REQUEST_WORKERS': '14',
        'MAX_CONCURRENT_REQUESTS': '16384',
        'ARQ_INITIAL_RTO_SECONDS': '0.3',
        'ARQ_MAX_RTO_SECONDS': '2.0',
        'ARQ_CONTROL_INITIAL_RTO_SECONDS': '0.3',
        'ARQ_CONTROL_MAX_RTO_SECONDS': '1.5',
        'MAX_PACKETS_PER_BATCH': '20',
        'PACKET_BLOCK_CONTROL_DUPLICATION': '3',
    }
    for key, val in optimized.items():
        save_server_config_value(key, val)
    return jsonify({'success': True, 'message': 'تنظیمات بهینه اعمال شد'})

# ============================================================
# Routes - Panel Settings
# ============================================================
@app.route('/api/change_password', methods=['POST'])
@login_required
def change_password():
    data = request.json or {}
    old_pass = data.get('old_password', '')
    new_pass = data.get('new_password', '')
    config = load_config()
    if hash_password(old_pass) != config['admin_password']:
        return jsonify({'error': 'پسورد فعلی اشتباه است'}), 400
    if len(new_pass) < 6:
        return jsonify({'error': 'پسورد جدید باید حداقل ۶ کاراکتر باشد'}), 400
    config['admin_password'] = hash_password(new_pass)
    save_config(config)
    return jsonify({'success': True})

if __name__ == '__main__':
    config = load_config()
    app.run(host='0.0.0.0', port=config.get('panel_port', 8888), debug=False)
