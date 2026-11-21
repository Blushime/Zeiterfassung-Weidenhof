import json
import os
import uuid
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from .datev import export_datev_unternehmen_online, export_entries_csv
from .decorators import admin_required, chef_required
from .extensions import db
from .importers import import_stempeluhr_xlsx
from .models import Abwesenheit, Abrechnungszeitraum, ImportBatch, Setting, TimeEntry, Urlaubsantrag, User
from .report import build_monthly_pdf
from .utils import (
    PERMISSIONS,
    entries_in_period,
    fmt_hhmm,
    get_or_create_period,
    ist_minuten,
    period_bounds,
    period_for,
    soll_minuten,
    urlaubskonto,
)

bp = Blueprint("admin", __name__)


@bp.route("/")
@login_required
@chef_required
def index():
    return render_template("admin/index.html")


# ---------- Benutzer ----------

@bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.name).all()
    return render_template("admin/users.html", users=all_users)


def _fill_user_from_form(user):
    user.email = (request.form.get("email") or "").strip().lower()
    user.name = (request.form.get("name") or "").strip()
    role = request.form.get("role") or "mitarbeiter"
    user.role = role if role in ("admin", "chef", "mitarbeiter") else "mitarbeiter"
    user.personalnummer = (request.form.get("personalnummer") or "").strip() or None
    user.department = (request.form.get("department") or "").strip() or None
    try:
        user.urlaubsanspruch_tage = float(request.form.get("urlaubsanspruch_tage") or 30)
    except ValueError:
        user.urlaubsanspruch_tage = 30.0
    try:
        user.soll_wochenstunden = float(request.form.get("soll_wochenstunden") or 40)
    except ValueError:
        user.soll_wochenstunden = 40.0
    user.aktiv = request.form.get("aktiv") == "1"
    pw = request.form.get("password") or ""
    if pw:
        user.set_password(pw)
    elif user.id is None:
        user.set_password(uuid.uuid4().hex)  # Zufalls-Passwort, Admin vergibt später eines
    return user


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def user_new():
    if request.method == "POST":
        user = _fill_user_from_form(User())
        db.session.add(user)
        try:
            db.session.commit()
            flash("Mitarbeiter angelegt.", "success")
            return redirect(url_for("admin.users"))
        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Anlegen: {e}", "danger")
    return render_template("admin/user_form.html", user=None)


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def user_edit(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if request.method == "POST":
        _fill_user_from_form(user)
        try:
            db.session.commit()
            flash("Mitarbeiter gespeichert.", "success")
            return redirect(url_for("admin.users"))
        except Exception as e:
            db.session.rollback()
            flash(f"Fehler beim Speichern: {e}", "danger")
    return render_template("admin/user_form.html", user=user)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def user_toggle(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("Das eigene Konto kann nicht deaktiviert werden.", "danger")
        return redirect(url_for("admin.users"))
    user.aktiv = not user.aktiv
    db.session.commit()
    flash(f"Konto {user.name} {'aktiviert' if user.aktiv else 'deaktiviert'}.", "info")
    return redirect(url_for("admin.users"))


# ---------- Abrechnungszeiträume ----------

@bp.route("/periods")
@login_required
@chef_required
def periods():
    items = Abrechnungszeitraum.query.order_by(
        Abrechnungszeitraum.jahr.desc(), Abrechnungszeitraum.monat.desc()
    ).all()
    return render_template("admin/periods.html", periods=items, now=datetime.now())


@bp.route("/periods/new", methods=["POST"])
@login_required
@chef_required
def period_new():
    try:
        jahr = int(request.form.get("jahr", 0))
        monat = int(request.form.get("monat", 0))
    except ValueError:
        flash("Ungültiger Zeitraum.", "danger")
        return redirect(url_for("admin.periods"))
    if not (1 <= monat <= 12) or jahr < 2000:
        flash("Ungültiger Zeitraum.", "danger")
        return redirect(url_for("admin.periods"))
    if period_for(jahr, monat):
        flash(f"Zeitraum {jahr}-{monat:02d} existiert bereits.", "info")
        return redirect(url_for("admin.periods"))
    p = Abrechnungszeitraum(jahr=jahr, monat=monat, status="offen")
    db.session.add(p)
    db.session.commit()
    flash(f"Zeitraum {p.name} angelegt.", "success")
    return redirect(url_for("admin.periods"))


def _set_period_status(pid, status):
    p = db.session.get(Abrechnungszeitraum, pid)
    if p is None:
        abort(404)
    if status == "offen" and p.status != "gesperrt":
        flash("Nur gesperrte Zeiträume können wieder geöffnet werden.", "danger")
        return redirect(url_for("admin.periods"))
    p.status = status
    if status in ("gesperrt", "abgerechnet"):
        p.geschlossen_am = datetime.now()
    db.session.commit()
    flash(f"Zeitraum {p.name}: {status}.", "success")
    return redirect(url_for("admin.periods"))


@bp.route("/periods/<int:pid>/sperren", methods=["POST"])
@login_required
@chef_required
def period_sperren(pid):
    return _set_period_status(pid, "gesperrt")


@bp.route("/periods/<int:pid>/entsperren", methods=["POST"])
@login_required
@chef_required
def period_entsperren(pid):
    return _set_period_status(pid, "offen")


@bp.route("/periods/<int:pid>/abrechnen", methods=["POST"])
@login_required
@chef_required
def period_abrechnen(pid):
    return _set_period_status(pid, "abgerechnet")


# ---------- Stempeluhr-Import ----------

@bp.route("/import", methods=["GET", "POST"])
@login_required
@chef_required
def import_upload():
    if request.method == "POST":
        f = request.files.get("datei")
        if f is None or f.filename == "":
            flash("Keine Datei ausgewählt.", "danger")
            return redirect(url_for("admin.import_upload"))
        filename = secure_filename(f.filename) or "import.xlsx"
        stored = f"{uuid.uuid4().hex}_{filename}"
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored)
        f.save(path)
        try:
            batch = import_stempeluhr_xlsx(path, current_user.id, filename=filename)
            flash(
                f"Import '{filename}': {batch.importiert} importiert, {batch.doppelt} doppelt, "
                f"{batch.fehler} Fehler, {batch.abwesenheit} Abwesenheit.",
                "success" if batch.fehler == 0 else "warning",
            )
            return redirect(url_for("admin.import_detail", batch_id=batch.id))
        except Exception as e:
            flash(f"Import fehlgeschlagen: {e}", "danger")
            return redirect(url_for("admin.import_upload"))
    batches = ImportBatch.query.order_by(ImportBatch.hochgeladen_am.desc()).all()
    return render_template("admin/import.html", batches=batches)


@bp.route("/import/<int:batch_id>")
@login_required
@chef_required
def import_detail(batch_id):
    batch = db.session.get(ImportBatch, batch_id)
    if batch is None:
        abort(404)
    try:
        log = json.loads(batch.log or "[]")
    except Exception:
        log = []
    return render_template("admin/batch_detail.html", batch=batch, log=log)


# ---------- Urlaubsgenehmigung ----------

@bp.route("/urlaub")
@login_required
@chef_required
def urlaub_all():
    antraege = Urlaubsantrag.query.order_by(Urlaubsantrag.created_at.desc()).all()
    return render_template("admin/urlaub.html", antraege=antraege)


def _set_urlaub_status(aid, status):
    a = db.session.get(Urlaubsantrag, aid)
    if a is None:
        abort(404)
    if a.status != "beantragt":
        flash("Antrag wurde bereits bearbeitet.", "info")
        return redirect(url_for("admin.urlaub_all"))
    a.status = status
    a.genehmigt_von = current_user.id
    a.genehmigt_am = datetime.now()
    db.session.commit()
    flash(f"Urlaubsantrag von {a.user.name}: {status}.", "success")
    return redirect(url_for("admin.urlaub_all"))


@bp.route("/urlaub/<int:aid>/genehmigen", methods=["POST"])
@login_required
@chef_required
def urlaub_genehmigen(aid):
    return _set_urlaub_status(aid, "genehmigt")


@bp.route("/urlaub/<int:aid>/ablehnen", methods=["POST"])
@login_required
@chef_required
def urlaub_ablehnen(aid):
    return _set_urlaub_status(aid, "abgelehnt")


# ---------- Übersicht aller Buchungen ----------

@bp.route("/entries")
@login_required
@chef_required
def entries_overview():
    now = datetime.now()
    user_id = request.args.get("user_id", type=int)
    jahr = request.args.get("jahr", type=int) or now.year
    monat = request.args.get("monat", type=int) or now.month
    period = period_for(jahr, monat) or get_or_create_period(datetime(jahr, monat, 1))
    s, e = period_bounds(period)
    q = TimeEntry.query.filter(TimeEntry.start >= s, TimeEntry.start < e)
    if user_id:
        q = q.filter_by(user_id=user_id)
    items = q.order_by(TimeEntry.start.desc()).all()
    users = User.query.order_by(User.name).all()
    return render_template(
        "admin/entries.html",
        entries=items,
        users=users,
        user_id=user_id,
        period=period,
        jahr=jahr,
        monat=monat,
        fmt_hhmm=fmt_hhmm,
    )


# ---------- Export ----------

@bp.route("/export")
@login_required
@chef_required
def export():
    periods = Abrechnungszeitraum.query.order_by(
        Abrechnungszeitraum.jahr.desc(), Abrechnungszeitraum.monat.desc()
    ).all()
    return render_template("admin/export.html", periods=periods)


@bp.route("/export/datev")
@login_required
@chef_required
def export_datev():
    jahr = request.args.get("jahr", type=int)
    monat = request.args.get("monat", type=int)
    period = period_for(jahr, monat)
    if period is None:
        flash("Bitte gültigen Zeitraum wählen.", "danger")
        return redirect(url_for("admin.export"))
    csv_data = export_datev_unternehmen_online(period)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=datev_unternehmen_online_{period.jahr}{period.monat:02d}.csv"
        },
    )


@bp.route("/export/entries")
@login_required
@chef_required
def export_entries():
    jahr = request.args.get("jahr", type=int)
    monat = request.args.get("monat", type=int)
    user_id = request.args.get("user_id", type=int)
    period = period_for(jahr, monat)
    if period is None:
        flash("Bitte gültigen Zeitraum wählen.", "danger")
        return redirect(url_for("admin.export"))
    csv_data = export_entries_csv(period, user_id=user_id)
    name = f"zeiten_{period.jahr}{period.monat:02d}" + (f"_pn{user_id}" if user_id else "") + ".csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={name}"},
    )


# ---------- Abwesenheiten (aus Stempeluhr) ----------

@bp.route("/absenzen")
@login_required
@chef_required
def absenzen():
    now = datetime.now()
    user_id = request.args.get("user_id", type=int)
    jahr = request.args.get("jahr", type=int) or now.year
    monat = request.args.get("monat", type=int) or now.month
    period = period_for(jahr, monat) or get_or_create_period(datetime(jahr, monat, 1))
    s, e = period_bounds(period)
    q = Abwesenheit.query.filter(Abwesenheit.datum >= s.date(), Abwesenheit.datum < e.date())
    if user_id:
        q = q.filter_by(user_id=user_id)
    items = q.order_by(Abwesenheit.datum.desc()).all()
    users = User.query.order_by(User.name).all()
    return render_template(
        "admin/absenzen.html",
        absenzen=items,
        users=users,
        user_id=user_id,
        period=period,
        jahr=jahr,
        monat=monat,
    )


# ---------- PDF-Monatsbericht (beliebiger Mitarbeiter) ----------

@bp.route("/report")
@login_required
@chef_required
def report():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        flash("Bitte Mitarbeiter wählen (z. B. über die Mitarbeiterliste).", "danger")
        return redirect(url_for("admin.users"))
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    now = datetime.now()
    jahr = request.args.get("jahr", type=int) or now.year
    monat = request.args.get("monat", type=int) or now.month
    period = period_for(jahr, monat) or get_or_create_period(datetime(jahr, monat, 1))
    entries = entries_in_period(user.id, period)
    s, e = period_bounds(period)
    absenzen = (
        Abwesenheit.query.filter(
            Abwesenheit.user_id == user.id, Abwesenheit.datum >= s.date(), Abwesenheit.datum < e.date()
        )
        .order_by(Abwesenheit.datum)
        .all()
    )
    ist = ist_minuten(user.id, period)
    soll = soll_minuten(user, period)
    konto = urlaubskonto(user, jahr)
    pdf = build_monthly_pdf(user, period, entries, absenzen, ist, soll, ist - soll, konto)
    fname = f"monatsbericht_{user.personalnummer or user.id}_{jahr}{monat:02d}.pdf"
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ---------- Einstellungen (DATEV, SMTP, Berechtigungen) ----------

SETTING_KEYS = [
    "datev_mandant",
    "datev_lohnart_default",
    "lohnarten_mapping",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_tls",
] + [f"perm_{k}" for k in PERMISSIONS]


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        for k in SETTING_KEYS:
            v = (request.form.get(k) or "").strip()
            s = Setting.query.filter_by(key=k).first()
            if s is None:
                s = Setting(key=k)
                db.session.add(s)
            s.value = v or None
        db.session.commit()
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("admin.settings"))
    values = {}
    for k in SETTING_KEYS:
        s = Setting.query.filter_by(key=k).first()
        values[k] = s.value if s and s.value else ""
    return render_template("admin/settings.html", values=values, permissions=PERMISSIONS)
