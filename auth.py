from functools import wraps
from flask import session, redirect, url_for, request


def current_user():
    user = session.get('user')
    if not user:
        return None
    return user


def login_user(username, role='user', is_guest=False):
    session['user'] = {
        'username': username,
        'role': role,
        'is_guest': is_guest,
    }


def logout_user():
    session.pop('user', None)
    session.pop('share_access', None)


def require_login(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for('login', next=request.path))
        if user.get('role') != 'admin':
            return redirect(url_for('index'))
        return view(*args, **kwargs)
    return wrapped
