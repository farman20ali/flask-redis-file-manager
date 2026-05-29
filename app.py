from io import BytesIO
from datetime import datetime, timedelta, timezone
import base64
import logging
import os
import re
import uuid

import bcrypt
import qrcode
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from auth import current_user, login_user, logout_user, require_admin, require_login
from file_python import File
from redis_client import Redis


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_secret_key')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_BYTES', 50 * 1024 * 1024))

server_address = os.getenv('REDIS_HOST', 'localhost')
redis_port = os.getenv('REDIS_PORT', '6379')
redis_pass = os.getenv('REDIS_PASSWORD', None)
if redis_pass == '':
    redis_pass = None

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')
GUEST_USERNAME = os.getenv('GUEST_USERNAME', 'guest')
FILE_DEFAULT_TTL_DAYS = int(os.getenv('FILE_DEFAULT_TTL_DAYS', '30'))
FILE_MAX_TTL_DAYS = int(os.getenv('FILE_MAX_TTL_DAYS', '365'))
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1048576))
PUBLIC_VISIBILITY = 'public'
PRIVATE_VISIBILITY = 'private'
FILES_PER_PAGE = int(os.getenv('FILES_PER_PAGE', 6))

redis_cli = Redis(server_address, redis_port, redis_pass)
file_helper = File()
_default_seed_done = False


def utcnow():
    return datetime.now(timezone.utc)


def isoformat(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def clamp_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = FILE_DEFAULT_TTL_DAYS
    return max(0, min(days, FILE_MAX_TTL_DAYS))


def clamp_hours(value):
    try:
        hours = int(value)
    except (TypeError, ValueError):
        hours = 1
    return max(1, min(hours, FILE_MAX_TTL_DAYS * 24))


def normalize_visibility(value):
    visibility = (value or PRIVATE_VISIBILITY).strip().lower()
    return PUBLIC_VISIBILITY if visibility == PUBLIC_VISIBILITY else PRIVATE_VISIBILITY


def parse_shared_with(raw_value):
    if not raw_value:
        return []
    return sorted(list({item.strip() for item in raw_value.split(',') if item.strip()}))


def format_shared_with(shared_with):
    return ','.join(sorted(list(set(shared_with))))


def parse_expiry_request(form_data):
    mode = (form_data.get('expiry_mode') or 'none').strip().lower()
    if mode == 'hours':
        hours = clamp_hours(form_data.get('expiry_hours', '1'))
        expiry_dt = utcnow() + timedelta(hours=hours)
        return isoformat(expiry_dt), max(1, int((expiry_dt - utcnow()).total_seconds()))
    if mode == 'custom':
        expiry_at = (form_data.get('expiry_at') or '').strip()
        if expiry_at:
            try:
                expiry_dt = datetime.fromisoformat(expiry_at)
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                expiry_dt = expiry_dt.astimezone(timezone.utc)
            except ValueError:
                expiry_dt = None
            if expiry_dt:
                return isoformat(expiry_dt), max(1, int((expiry_dt - utcnow()).total_seconds()))
        return '', 0
    days = clamp_days(form_data.get('expiry_days', FILE_DEFAULT_TTL_DAYS))
    if days <= 0:
        return '', 0
    expiry_dt = utcnow() + timedelta(days=days)
    return isoformat(expiry_dt), max(1, int((expiry_dt - utcnow()).total_seconds()))


def sanitize_filename(filename):
    if not filename:
        return None
    filename = secure_filename(filename)
    filename = re.sub(r'[^\w\s\-\.]', '', filename)
    if len(filename) > 255:
        filename = filename[:255]
    return filename if filename else None


def validate_username(username):
    return bool(username and re.match(r'^[\w\-]+$', username))


def validate_password(password):
    return password is not None and len(password) >= 6


def build_storage_key(owner, filename):
    return f'file_{owner}_{filename}'


def build_share_key(token):
    return f'share:{token}'


def resolve_owner(form_data):
    selected_owner = (form_data.get('send_to') or '').strip()
    if validate_username(selected_owner):
        return selected_owner
    return current_username()


def generate_qr_data_uri(url):
    qr = qrcode.make(url)
    buffer = BytesIO()
    qr.save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('utf-8')


def current_actor():
    return current_user()


def current_username():
    actor = current_actor()
    return actor['username'] if actor else None


def current_role():
    actor = current_actor()
    return actor['role'] if actor else None


def is_admin_user():
    return current_role() == 'admin'


def grant_file_access(storage_key):
    access = session.get('file_access', {})
    access[storage_key] = True
    session['file_access'] = access
    session.modified = True


def has_file_access(storage_key):
    return session.get('file_access', {}).get(storage_key, False)


def ensure_connected():
    if not redis_cli.isConnected():
        redis_cli.connect()
    return redis_cli.isConnected()


def seed_default_admin():
    global _default_seed_done
    if _default_seed_done:
        return
    ensure_connected()
    existing = redis_cli.getUser(ADMIN_USERNAME)
    if not existing:
        redis_cli.createOrUpdateUser(ADMIN_USERNAME, ADMIN_PASSWORD, role='admin', active='1')
        logger.info('Seeded default admin account')
    _default_seed_done = True


def file_is_expired(meta):
    expires_at = parse_dt(meta.get('expires_at'))
    return expires_at is not None and utcnow() > expires_at


def remove_file_bundle(storage_key):
    meta = redis_cli.getFileMeta(storage_key)
    share_token = meta.get('share_token') if meta else None
    redis_cli.deleteFileBundle(storage_key)
    if share_token:
        redis_cli.deleteKeys(build_share_key(share_token))


def store_encoded_file(owner, filename, encoded_data, *, file_password='', expiry_days=0, uploaded_by=None, source='file', visibility=PRIVATE_VISIBILITY, expires_at=''):
    storage_key = build_storage_key(owner, filename)
    if redis_cli.key_exists(storage_key):
        return None, storage_key

    token = uuid.uuid4().hex
    now = utcnow()
    seconds = 0
    expiry_dt = parse_dt(expires_at)
    if expiry_dt:
        seconds = max(0, int((expiry_dt - utcnow()).total_seconds()))
    elif expiry_days:
        seconds = int(expiry_days) * 86400
    password_hash = ''
    if file_password:
        password_hash = bcrypt.hashpw(file_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    for start in range(0, len(encoded_data), CHUNK_SIZE):
        redis_cli.appendRpush(storage_key, encoded_data[start:start + CHUNK_SIZE])

    meta = {
        'storage_key': storage_key,
        'owner': owner,
        'filename': filename,
        'uploaded_by': uploaded_by or owner,
        'source': source,
        'share_token': token,
        'created_at': isoformat(now),
        'expires_at': expires_at,
        'password_hash': password_hash,
        'visibility': normalize_visibility(visibility),
        'shared_with': '',
        'size_bytes': str(len(base64.b64decode(encoded_data.encode('utf-8')))),
    }
    redis_cli.setFileMeta(storage_key, meta)
    redis_cli.setKey(build_share_key(token), storage_key)

    if seconds > 0:
        redis_cli.setExpiry(storage_key, seconds)
        redis_cli.setExpiry(f'filemeta:{storage_key}', seconds)
        redis_cli.setExpiry(build_share_key(token), seconds)

    return meta, storage_key


def get_retrieved_text_key():
    actor = current_actor()
    if not actor:
        return 'saved_text'
    return f"saved_text:{actor['username']}"


def get_text():
    text_key = get_retrieved_text_key()
    if not redis_cli.key_exists(text_key):
        return 'No text found in Redis.'
    text = redis_cli.getKey(text_key)
    if not text:
        return 'No text found in Redis.'
    return text


def file_requires_password(meta):
    return bool(meta and meta.get('password_hash'))


def can_access_file(meta):
    actor = current_actor()
    if not actor:
        return meta.get('visibility') == PUBLIC_VISIBILITY
    if actor.get('role') == 'admin':
        return True
    if meta.get('owner') == actor.get('username'):
        return True
    shared_with = parse_shared_with(meta.get('shared_with', ''))
    if actor.get('username') in shared_with:
        return True
    return meta.get('visibility') == PUBLIC_VISIBILITY


def generate_file_records():
    ensure_connected()
    records = []
    for meta_key in redis_cli.listFileMetaKeys():
        meta = redis_cli.getHash(meta_key)
        if not meta:
            continue
        storage_key = meta.get('storage_key') or meta_key.replace('filemeta:', '', 1)
        if not redis_cli.key_exists(storage_key):
            redis_cli.deleteKeys(meta_key)
            continue
        if file_is_expired(meta):
            remove_file_bundle(storage_key)
            continue
        if not can_access_file(meta):
            continue
        share_token = meta.get('share_token') or ''
        share_url = url_for('share_file', token=share_token, _external=True) if share_token else ''
        records.append({
            'storage_key': storage_key,
            'filename': meta.get('filename', 'download'),
            'owner': meta.get('owner', 'unknown'),
            'uploaded_by': meta.get('uploaded_by', meta.get('owner', 'unknown')),
            'source': meta.get('source', 'file'),
            'visibility': meta.get('visibility', PRIVATE_VISIBILITY),
            'shared_with': parse_shared_with(meta.get('shared_with', '')),
            'created_at': meta.get('created_at', ''),
            'expires_at': meta.get('expires_at', ''),
            'size_bytes': int(meta.get('size_bytes', '0')),
            'password_protected': bool(meta.get('password_hash')),
            'share_token': share_token,
            'share_url': share_url,
            'qr_data_uri': generate_qr_data_uri(share_url) if share_url else '',
            'ttl_seconds': redis_cli.getTTL(storage_key),
        })

    records.sort(key=lambda item: item.get('created_at') or '', reverse=True)
    return records


def update_file_list(send_to=None, role=None):
    return generate_file_records()


def paginate_records(records, page, per_page):
    total = len(records)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    return records[start:end], page, total_pages, total


def render_dashboard():
    page = request.args.get('page', 1, type=int)
    files = update_file_list(current_username(), current_role())
    paged_files, page, total_pages, total_files = paginate_records(files, page, FILES_PER_PAGE)
    users = redis_cli.listUsers()
    return render_template(
        'dashboard.html',
        files=paged_files,
        users=users,
        retrieved_text=get_text(),
        max_ttl_days=FILE_MAX_TTL_DAYS,
        current_user=current_actor(),
        theme_options=['default', 'light', 'calm'],
        page=page,
        total_pages=total_pages,
        total_files=total_files,
        files_per_page=FILES_PER_PAGE,
        prev_page=page - 1 if page > 1 else None,
        next_page=page + 1 if page < total_pages else None,
    )


def decode_file_payload(encoded_data):
    if isinstance(encoded_data, list):
        encoded_data = ''.join(encoded_data)
    return base64.b64decode(encoded_data.encode('utf-8'))


def send_storage_file(storage_key):
    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        abort(404)
    if file_is_expired(meta):
        remove_file_bundle(storage_key)
        abort(404)
    if not redis_cli.key_exists(storage_key):
        abort(404)

    encoded_data = redis_cli.getKey(storage_key)
    if encoded_data is None:
        abort(404)

    filename = meta.get('filename') or 'download'
    decoded_data = decode_file_payload(encoded_data)
    return send_file(BytesIO(decoded_data), as_attachment=True, download_name=filename)


def prepare_password_prompt(storage_key, token=None):
    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        abort(404)
    return render_template(
        'password_prompt.html',
        storage_key=storage_key,
        token=token or '',
        filename=meta.get('filename', 'download'),
        owner=meta.get('owner', 'unknown'),
    )


def handle_file_password_guard(storage_key, token=None):
    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        abort(404)
    if not file_requires_password(meta):
        return None
    if has_file_access(storage_key):
        return None
    return prepare_password_prompt(storage_key, token=token)


@app.before_request
def before_request():
    ensure_connected()
    seed_default_admin()
    g.current_user = current_actor()


@app.context_processor
def inject_context():
    return {
        'current_user': current_actor(),
        'is_admin_user': is_admin_user,
        'get_text': get_text,
        'theme_name': session.get('theme', 'default'),
    }


@app.route('/theme/<theme_name>')
@require_login
def set_theme(theme_name):
    if theme_name not in {'default', 'light', 'calm'}:
        theme_name = 'default'
    session['theme'] = theme_name
    next_url = request.referrer or url_for('index')
    return redirect(next_url)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form.get('action', 'login')
        if action == 'guest':
            login_user(GUEST_USERNAME, role='guest', is_guest=True)
            flash('Entered as guest.', 'success')
            return redirect(url_for('index'))

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not validate_username(username):
            flash('Invalid username.', 'error')
            return render_template('login.html')

        if redis_cli.verifyUserPassword(username, password):
            user = redis_cli.getUser(username) or {}
            role = user.get('role', 'user')
            login_user(username, role=role, is_guest=(role == 'guest'))
            flash(f'Welcome, {username}.', 'success')
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)

        flash('Invalid username or password.', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))


@app.route('/', methods=['GET', 'POST'])
@require_login
def index():
    if request.method == 'POST':
        try:
            actor = current_actor()
            upload_owner = resolve_owner(request.form)
            if not validate_username(upload_owner):
                flash('Invalid upload owner.', 'error')
                return redirect(url_for('index'))

            expires_at, expiry_seconds = parse_expiry_request(request.form)
            file_password = request.form.get('file_password', '').strip()
            if file_password and not validate_password(file_password):
                flash('File password must be at least 6 characters.', 'error')
                return redirect(url_for('index'))
            visibility = normalize_visibility(request.form.get('visibility'))

            encoded_data = None
            filename = None
            source = 'file'

            if 'folder' in request.files:
                files = request.files.getlist('folder')
                encoded_data = file_helper.zip_in_memory_fileStorage(files)
                filename = request.form.get('filename', '').strip()
                if filename:
                    filename = sanitize_filename(filename)
                    if filename:
                        filename = filename + '.zip'
                source = 'folder'
            elif 'file' in request.files:
                uploaded_file = request.files['file']
                if uploaded_file and uploaded_file.filename:
                    filename = sanitize_filename(uploaded_file.filename)
                    encoded_data = base64.b64encode(uploaded_file.read()).decode('utf-8')

            if encoded_data is None:
                flash('Please select a file or folder to upload.', 'error')
                return redirect(url_for('index'))
            if not filename:
                flash('Invalid filename.', 'error')
                return redirect(url_for('index'))

            storage_key = build_storage_key(upload_owner, filename)
            if redis_cli.key_exists(storage_key):
                return render_template(
                    'file_exists.html',
                    send_to=upload_owner,
                    filename=filename,
                    encoded_data=encoded_data,
                    expiry_at=expires_at,
                    expiry_seconds=expiry_seconds,
                    file_password=file_password,
                    visibility=visibility,
                    source=source,
                )

            meta, _ = store_encoded_file(
                upload_owner,
                filename,
                encoded_data,
                file_password=file_password,
                expiry_days=0,
                uploaded_by=actor['username'],
                source=source,
                visibility=visibility,
                expires_at=expires_at,
            )
            if not meta:
                flash('A file with the same name already exists.', 'error')
                return redirect(url_for('index'))

            flash(f"File '{filename}' uploaded successfully.", 'success')
            return redirect(url_for('index'))
        except Exception as exc:
            logger.error(f'Error in index upload: {exc}')
            flash('An error occurred while uploading the file.', 'error')
            return redirect(url_for('index'))

    return render_dashboard()


@app.route('/save-text', methods=['POST'])
@require_login
def save_text():
    try:
        actor = current_actor()
        text = request.form.get('text', '')
        if not text:
            flash('Text is required.', 'error')
            return redirect(url_for('index'))

        save_as_file = 'save_as_file' in request.form
        if save_as_file:
            filename = sanitize_filename(request.form.get('text_filename', 'save-text.txt')) or 'save-text.txt'
            if not filename.endswith('.txt'):
                filename = f'{filename}.txt'
            expires_at, _expiry_seconds = parse_expiry_request(request.form)
            file_password = request.form.get('file_password', '').strip()
            if file_password and not validate_password(file_password):
                flash('File password must be at least 6 characters.', 'error')
                return redirect(url_for('index'))
            visibility = normalize_visibility(request.form.get('visibility'))

            encoded_data = base64.b64encode(text.encode('utf-8')).decode('utf-8')
            meta, _ = store_encoded_file(
                actor['username'],
                filename,
                encoded_data,
                file_password=file_password,
                expiry_days=0,
                uploaded_by=actor['username'],
                source='text',
                visibility=visibility,
                expires_at=expires_at,
            )
            if not meta:
                flash('A file with the same name already exists.', 'error')
                return redirect(url_for('index'))
            flash(f"Text saved as '{filename}'.", 'success')
            return redirect(url_for('index'))

        redis_cli.setKey(get_retrieved_text_key(), text)
        flash('Text saved successfully.', 'success')
        return redirect(url_for('index'))
    except Exception as exc:
        logger.error(f'Error in save_text: {exc}')
        flash('An error occurred while saving text.', 'error')
        return redirect(url_for('index'))


@app.route('/download-text', methods=['POST'])
@require_login
def download_retrieved_text():
    retrieved_text = request.form['retrieved_text']
    return send_file(BytesIO(retrieved_text.encode()), as_attachment=True, download_name='retrieved_text.txt', mimetype='text/plain')


@app.route('/get-text', methods=['GET'])
@require_login
def get_text_route():
    return render_dashboard()


@app.route('/download', methods=['POST'])
@require_login
def download():
    selected_option = request.form.get('selected_option', '')
    if not selected_option:
        flash('No file selected.', 'error')
        return redirect(url_for('index'))

    meta = redis_cli.getFileMeta(selected_option)
    if not meta:
        abort(404)
    if not can_access_file(meta):
        abort(403)

    password_guard = handle_file_password_guard(selected_option)
    if password_guard is not None:
        return password_guard

    return send_storage_file(selected_option)


@app.route('/share/<token>', methods=['GET'])
def share_file(token):
    storage_key = redis_cli.getKey(build_share_key(token))
    if not storage_key:
        abort(404)

    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        abort(404)
    if file_is_expired(meta):
        remove_file_bundle(storage_key)
        abort(404)

    password_guard = handle_file_password_guard(storage_key, token=token)
    if password_guard is not None:
        return password_guard

    return send_storage_file(storage_key)


@app.route('/verify-password', methods=['POST'])
def verify_password():
    storage_key = request.form.get('storage_key', '')
    password = request.form.get('password', '')
    token = request.form.get('token', '')

    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        abort(404)

    password_hash = meta.get('password_hash', '')
    if not password_hash or not bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
        flash('Invalid file password.', 'error')
        return redirect(url_for('share_file', token=token) if token else url_for('index'))

    grant_file_access(storage_key)
    return send_storage_file(storage_key)


@app.route('/overwrite', methods=['POST'])
@require_login
def overwrite():
    try:
        actor = current_actor()
        send_to = request.form.get('send_to', '')
        filename = sanitize_filename(request.form.get('filename', ''))
        encoded_data = request.form.get('encoded_data', '')
        expiry_at = request.form.get('expiry_at', '').strip()
        visibility = normalize_visibility(request.form.get('visibility'))
        file_password = request.form.get('file_password', '').strip()

        if not filename:
            flash('Invalid filename.', 'error')
            return redirect(url_for('index'))

        owner = send_to if is_admin_user() and validate_username(send_to) else actor['username']
        storage_key = build_storage_key(owner, filename)
        redis_cli.deleteFileBundle(storage_key)

        meta, _ = store_encoded_file(
            owner,
            filename,
            encoded_data,
            file_password=file_password,
            expiry_days=0,
            uploaded_by=actor['username'],
            source='overwrite',
            visibility=visibility,
            expires_at=expiry_at,
        )
        if not meta:
            flash('Unable to overwrite the file.', 'error')
            return redirect(url_for('index'))

        flash(f"File '{filename}' overwritten successfully.", 'success')
        return redirect(url_for('index'))
    except Exception as exc:
        logger.error(f'Error in overwrite: {exc}')
        flash('An error occurred while overwriting the file.', 'error')
        return redirect(url_for('index'))


@app.route('/rename', methods=['POST'])
@require_login
def rename():
    try:
        actor = current_actor()
        send_to = request.form.get('send_to', '')
        encoded_data = request.form.get('encoded_data', '')
        new_filename = sanitize_filename(request.form.get('new_filename', ''))
        expiry_at = request.form.get('expiry_at', '').strip()
        visibility = normalize_visibility(request.form.get('visibility'))
        file_password = request.form.get('file_password', '').strip()

        if not new_filename:
            flash('New filename required.', 'error')
            return redirect(url_for('index'))

        owner = send_to if is_admin_user() and validate_username(send_to) else actor['username']
        storage_key = build_storage_key(owner, new_filename)
        if redis_cli.key_exists(storage_key):
            return render_template(
                'file_exists.html',
                send_to=owner,
                filename=new_filename,
                encoded_data=encoded_data,
                expiry_at=expiry_at,
                file_password=file_password,
                visibility=visibility,
                source='rename',
            )

        meta, _ = store_encoded_file(
            owner,
            new_filename,
            encoded_data,
            file_password=file_password,
            expiry_days=0,
            uploaded_by=actor['username'],
            source='rename',
            visibility=visibility,
            expires_at=expiry_at,
        )
        if not meta:
            flash('Unable to rename the file.', 'error')
            return redirect(url_for('index'))

        flash(f"File '{new_filename}' renamed successfully.", 'success')
        return redirect(url_for('index'))
    except Exception as exc:
        logger.error(f'Error in rename: {exc}')
        flash('An error occurred while renaming the file.', 'error')
        return redirect(url_for('index'))


@app.route('/delete-file', methods=['POST'])
@require_login
def delete_file():
    storage_key = request.form.get('storage_key', '')
    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        abort(404)
    if not is_admin_user() and meta.get('owner') != current_username():
        abort(403)
    remove_file_bundle(storage_key)
    flash('File deleted successfully.', 'success')
    return redirect(url_for('index'))


@app.route('/share-with-user', methods=['POST'])
@require_login
def share_with_user():
    storage_key = request.form.get('storage_key', '').strip()
    share_username = request.form.get('share_username', '').strip()
    action = request.form.get('action', 'add').strip().lower()

    if not storage_key:
        flash('Missing file selection for sharing.', 'error')
        return redirect(url_for('index'))

    meta = redis_cli.getFileMeta(storage_key)
    if not meta:
        flash('File not found.', 'error')
        return redirect(url_for('index'))

    actor = current_actor()
    if not actor:
        abort(403)
    if actor.get('role') != 'admin' and meta.get('owner') != actor.get('username'):
        abort(403)

    shared_with = parse_shared_with(meta.get('shared_with', ''))

    if action == 'remove':
        if share_username in shared_with:
            shared_with.remove(share_username)
            redis_cli.setFileMeta(storage_key, {'shared_with': format_shared_with(shared_with)})
            flash(f'Removed access for {share_username}.', 'success')
        else:
            flash('User was not in shared list.', 'warning')
        return redirect(url_for('index'))

    if not validate_username(share_username):
        flash('Select a valid user to share with.', 'error')
        return redirect(url_for('index'))

    if share_username == meta.get('owner'):
        flash('Owner already has access.', 'warning')
        return redirect(url_for('index'))

    target_user = redis_cli.getUser(share_username)
    if not target_user:
        flash('Selected user does not exist.', 'error')
        return redirect(url_for('index'))

    if share_username not in shared_with:
        shared_with.append(share_username)
        redis_cli.setFileMeta(storage_key, {'shared_with': format_shared_with(shared_with)})
        flash(f'File shared with {share_username}.', 'success')
    else:
        flash(f'File already shared with {share_username}.', 'warning')

    return redirect(url_for('index'))


@app.route('/admin/users', methods=['GET', 'POST'])
@require_admin
def admin_users():
    if request.method == 'POST':
        action = request.form.get('action', '')
        username = request.form.get('username', '').strip()

        if action == 'create':
            password = request.form.get('password', '')
            role = request.form.get('role', 'user')
            if not validate_username(username):
                flash('Invalid username.', 'error')
            elif not validate_password(password):
                flash('Password must be at least 6 characters.', 'error')
            else:
                redis_cli.createOrUpdateUser(username, password, role=role, active='1')
                flash(f'User {username} created.', 'success')

        elif action == 'update':
            role = request.form.get('role', 'user')
            active = request.form.get('active', '1')
            password = request.form.get('password', '').strip()
            if not validate_username(username):
                flash('Invalid username.', 'error')
            else:
                fields = {'role': role, 'active': active}
                if password:
                    if not validate_password(password):
                        flash('Password must be at least 6 characters.', 'error')
                        return redirect(url_for('admin_users'))
                    fields['password_hash'] = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                redis_cli.updateUser(username, **fields)
                flash(f'User {username} updated.', 'success')

        elif action == 'delete':
            if username == ADMIN_USERNAME:
                flash('Cannot delete the seeded admin user.', 'error')
            else:
                redis_cli.deleteUserRecord(username)
                flash(f'User {username} deleted.', 'success')

        return redirect(url_for('admin_users'))

    return render_template('admin_users.html', users=redis_cli.listUsers(), current_user=current_actor())


@app.errorhandler(403)
def forbidden(_error):
    return render_template('login.html', error_message='You do not have permission to access that resource.'), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template('login.html', error_message='The requested resource was not found.'), 404


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(debug=debug_mode, host=host, port=port)
