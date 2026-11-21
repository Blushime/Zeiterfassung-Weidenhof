from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user

from .utils import permission_enabled


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not (current_user.is_authenticated and current_user.is_admin):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def chef_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not (current_user.is_authenticated and current_user.is_chef):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def permission_required(name):
    """Sperrt eine Funktion, wenn die Berechtigung in den Admin-Einstellungen deaktiviert ist."""

    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not (current_user.is_authenticated and permission_enabled(name)):
                flash("Diese Funktion ist aktuell deaktiviert (Berechtigung nicht freigeschaltet).", "warning")
                return redirect(url_for("main.dashboard"))
            return view(*args, **kwargs)

        return wrapped

    return deco
