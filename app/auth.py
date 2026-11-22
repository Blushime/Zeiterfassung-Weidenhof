from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, login_required, logout_user

from .extensions import db
from .models import User

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user and user.aktiv and user.check_password(password):
            login_user(user)
            flash("Erfolgreich angemeldet.", "success")
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("main.dashboard"))
        flash("E-Mail oder Passwort falsch — oder das Konto ist deaktiviert.", "danger")
    user_count = User.query.count()
    return render_template("auth/login.html", user_count=user_count)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Abgemeldet.", "info")
    return redirect(url_for("auth.login"))
