import json
import os
import uuid
from datetime import date, datetime, timedelta

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
    parse_time,
    permission_enabled,
    period_bounds,
    period_for,
    soll_minuten,
    urlaub_modus,
    urlaubskonto,
    user_perm_override,
    user_plan_days,
)

PERM_SHORT = {"timer": "Timer", "manual": "Manuell", "edit": "Zeitpassung"}


def _perm_summary(user):
    parts = []
    for k in PERMISSIONS:
        ov = user_perm_override(user, k)
        if ov == "1":
            parts.append(f"{PERM_SHORT.get(k, k)}: an")
        elif ov == "0":
            parts.append(f"{PERM_SHORT.get(k, k)}: aus")
    return ", ".join(parts) if parts else "Standard"

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
    perm_summary = {u.id: _perm_summary(u) for u in all_users}
    plan_labels = {u.id: ", ".join(PLAN_NAMES[d] for d in sorted(user_plan_days(u))) for u in all_users}
    return render_template("admin/users.html", users=all_users, perm_summary=perm_summary, plan_labels=plan_labels)


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
    modus = request.form.get("urlaub_modus") or "konto"
    user.urlaub_modus = modus if modus in ("konto", "auszahlung") else "konto"
    try:
        user.urlaub_stunden_pro_tag = float(request.form.get("urlaub_stunden_pro_tag") or 8)
    except ValueError:
        user.urlaub_stunden_pro_tag = 8.0
    # Soll-Stunden pro Monat: individuell pro Mitarbeiter (leer = global vom Abrechnungszeitraum)
    user.hat_soll = request.form.get("hat_soll") == "1"
    raw_soll = (request.form.get("soll_stunden_monat") or "").strip()
    if raw_soll:
        try:
            user.soll_stunden_monat = float(raw_soll.replace(",", "."))
        except ValueError:
            user.soll_stunden_monat = None
    else:
        user.soll_stunden_monat = None
    # Arbeitsplan: Wochentage als Checkboxen (0=Mo .. 6=So); leer = Mo-Fr (Default)
    plan = sorted({int(x) for x in request.form.getlist("plan") if x.strip().isdigit()})
    user.arbeitsplan = ",".join(str(d) for d in plan) if plan else "0,1,2,3,4"
    user.aktiv = request.form.get("aktiv") == "1"
    # Berechtigungs-Overrides pro Mitarbeiter ("" = globale Einstellung aus den Settings)
    overrides = {}
    for key in PERMISSIONS:
        v = (request.form.get(f"perm_{key}") or "").strip()
        if v in ("0", "1"):
            overrides[key] = v
    user.perm_overrides = json.dumps(overrides, ensure_ascii=False) if overrides else None
    pw = request.form.get("password") or ""
    if pw:
        user.set_password(pw)
    elif user.id is None:
        user.set_password(uuid.uuid4().hex)  # Zufalls-Passwort, Admin vergibt später eines
    return user


def _perm_form_context(user):
    perm_values = {k: (user_perm_override(user, k) or "") for k in PERMISSIONS} if user else {}
    global_perms = {k: permission_enabled(k) for k in PERMISSIONS}
    return {"permissions": PERMISSIONS, "perm_values": perm_values, "global_perms": global_perms}


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
    return render_template("admin/user_form.html", user=None, **_perm_form_context(None))


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
    return render_template("admin/user_form.html", user=user, **_perm_form_context(user))


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


def _parse_soll_stunden():
    raw = (request.form.get("soll_stunden") or "").strip()
    if not raw:
        return None
    return float(raw.replace(",", "."))


@bp.route("/periods/new", methods=["POST"])
@login_required
@chef_required
def period_new():
    try:
        jahr = int(request.form.get("jahr", 0))
        monat = int(request.form.get("monat", 0))
        soll = _parse_soll_stunden()
    except ValueError:
        flash("Ungültiger Zeitraum / ungültige Soll-Stunden.", "danger")
        return redirect(url_for("admin.periods"))
    if not (1 <= monat <= 12) or jahr < 2000:
        flash("Ungültiger Zeitraum.", "danger")
        return redirect(url_for("admin.periods"))
    if period_for(jahr, monat):
        flash(f"Zeitraum {jahr}-{monat:02d} existiert bereits.", "info")
        return redirect(url_for("admin.periods"))
    p = Abrechnungszeitraum(jahr=jahr, monat=monat, status="offen", soll_stunden=soll)
    db.session.add(p)
    db.session.commit()
    flash(f"Zeitraum {p.name} angelegt (Soll: {soll} h/Monat)." if soll else f"Zeitraum {p.name} angelegt.", "success")
    return redirect(url_for("admin.periods"))


@bp.route("/periods/<int:pid>/edit", methods=["POST"])
@login_required
@chef_required
def period_edit(pid):
    """Soll-Stunden (Monat) eines Zeitraums nachträglich ändern (nur wenn nicht abgerechnet)."""
    p = db.session.get(Abrechnungszeitraum, pid)
    if p is None:
        abort(404)
    if p.status == "abgerechnet":
        flash("Abgerechneter Zeitraum kann nicht mehr geändert werden.", "danger")
        return redirect(url_for("admin.periods"))
    try:
        p.soll_stunden = _parse_soll_stunden()
    except ValueError:
        flash("Ungültige Soll-Stunden.", "danger")
        return redirect(url_for("admin.periods"))
    db.session.commit()
    flash(f"Soll-Stunden für {p.name} gespeichert: {p.soll_stunden} h" if p.soll_stunden else f"Soll-Stunden für {p.name} entfernt (Fallback).", "success")
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


# ---------- Mitarbeiter-Stände (alles, was der Mitarbeiter selbst sieht) ----------

@bp.route("/mitarbeiter/<int:user_id>")
@login_required
@chef_required
def mitarbeiter_detail(user_id):
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
    konto = urlaubskonto(user, now.year)
    antraege = (
        Urlaubsantrag.query.filter_by(user_id=user.id).order_by(Urlaubsantrag.von.desc()).limit(20).all()
    )
    return render_template(
        "admin/mitarbeiter_detail.html",
        user=user,
        period=period,
        entries=entries,
        absenzen=absenzen,
        ist=ist,
        soll=soll,
        saldo=ist - soll,
        konto=konto,
        antraege=antraege,
        urlaub_modus=urlaub_modus(user),
        fmt_hhmm=fmt_hhmm,
        jahr=jahr,
        monat=monat,
    )


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


# ---------- Buchung eines Mitarbeiters bearbeiten (Admin/Chef) ----------

@bp.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
@chef_required
def entry_edit(entry_id):
    entry = db.session.get(TimeEntry, entry_id)
    if entry is None:
        abort(404)
    p = period_for(entry.start.year, entry.start.month)
    if request.method == "POST":
        if p and p.gesperrt:
            flash("Zeitraum gesperrt — Änderung nicht möglich.", "danger")
            return redirect(url_for("admin.entries_overview", jahr=p.jahr, monat=p.monat, user_id=entry.user_id))
        try:
            d = datetime.strptime(request.form.get("datum", ""), "%Y-%m-%d").date()
        except ValueError:
            flash("Ungültiges Datum.", "danger")
            return redirect(url_for("admin.entry_edit", entry_id=entry_id))
        von = parse_time(request.form.get("von", ""))
        bis = parse_time(request.form.get("bis", ""))
        if von is None or bis is None:
            flash("Ungültige Uhrzeit (Format HH:MM).", "danger")
            return redirect(url_for("admin.entry_edit", entry_id=entry_id))
        start = datetime.combine(d, von)
        ende = datetime.combine(d, bis)
        if ende <= start:
            ende += timedelta(days=1)
        entry.start = start
        entry.ende = ende
        entry.dauer_minuten = int((ende - start).total_seconds() // 60)
        entry.kategorie = (request.form.get("kategorie") or "Allgemein").strip() or "Allgemein"
        entry.bemerkung = (request.form.get("bemerkung") or "").strip() or None
        try:
            db.session.commit()
            flash(f"Buchung von {entry.user.name} angepasst.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Änderung nicht möglich: {e}", "danger")
        return redirect(url_for("admin.entries_overview", jahr=start.year, monat=start.month, user_id=entry.user_id))
    return render_template("admin/entry_form.html", entry=entry)


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


ABSENZ_TYPEN = ["Urlaub", "Krank", "Sonstiges"]
PLAN_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _period_locked(d: date) -> bool:
    p = period_for(d.year, d.month)
    return bool(p and p.status in ("gesperrt", "abgerechnet"))


@bp.route("/absenzen/new", methods=["GET", "POST"])
@login_required
@chef_required
def absenz_new():
    """Abwesenheit(en) manuell anlegen — Von/Bis wird auf die Arbeitsplan-Tage des Mitarbeiters aufgeteilt."""
    users = User.query.filter_by(aktiv=True).order_by(User.name).all()
    if request.method == "POST":
        try:
            user_id = int(request.form.get("user_id", 0))
            von = datetime.strptime(request.form.get("von", ""), "%Y-%m-%d").date()
            bis = datetime.strptime(request.form.get("bis", ""), "%Y-%m-%d").date()
        except ValueError:
            flash("Ungültige Eingabe (Mitarbeiter/Datum).", "danger")
            return redirect(url_for("admin.absenz_new"))
        user = db.session.get(User, user_id)
        if user is None:
            flash("Mitarbeiter nicht gefunden.", "danger")
            return redirect(url_for("admin.absenz_new"))
        if bis < von:
            flash("Bis-Datum liegt vor Von-Datum.", "danger")
            return redirect(url_for("admin.absenz_new"))
        typ = (request.form.get("typ") or "Sonstiges").strip() or "Sonstiges"
        if typ not in ABSENZ_TYPEN:
            typ = "Sonstiges"
        bemerkung = (request.form.get("bemerkung") or "").strip() or None
        plan = user_plan_days(user)
        created = skipped_locked = skipped_dup = 0
        d = von
        while d <= bis:
            if d.weekday() in plan:  # nur Arbeitsplan-Tage zählen als Abwesenheitstag
                if _period_locked(d):
                    skipped_locked += 1
                elif Abwesenheit.query.filter_by(user_id=user.id, datum=d).first():
                    skipped_dup += 1
                else:
                    db.session.add(
                        Abwesenheit(user_id=user.id, datum=d, typ=typ, quelle="manuell", bemerkung=bemerkung)
                    )
                    created += 1
            d += timedelta(days=1)
        db.session.commit()
        msg = f"Abwesenheit '{typ}' für {user.name} angelegt: {created} Tag(e)."
        if skipped_dup:
            msg += f" {skipped_dup} bereits vorhanden (übersprungen)."
        if skipped_locked:
            msg += f" {skipped_locked} in gesperrten Zeiträumen (übersprungen)."
        flash(msg, "success" if created else "warning")
        return redirect(url_for("admin.absenzen", user_id=user.id, jahr=von.year, monat=von.month))
    preselect = request.args.get("user_id", type=int)
    return render_template(
        "admin/absenz_form.html", users=users, absenz=None, typen=ABSENZ_TYPEN,
        preselect=preselect, today=date.today().isoformat(),
    )


@bp.route("/absenzen/<int:aid>/edit", methods=["GET", "POST"])
@login_required
@chef_required
def absenz_edit(aid):
    a = db.session.get(Abwesenheit, aid)
    if a is None:
        abort(404)
    if request.method == "POST":
        if _period_locked(a.datum):
            flash("Zeitraum gesperrt/abgerechnet — Änderung nicht möglich.", "danger")
            return redirect(url_for("admin.absenzen", jahr=a.datum.year, monat=a.datum.month))
        try:
            new_datum = datetime.strptime(request.form.get("datum", ""), "%Y-%m-%d").date()
        except ValueError:
            flash("Ungültiges Datum.", "danger")
            return redirect(url_for("admin.absenz_edit", aid=aid))
        if _period_locked(new_datum):
            flash("Zieldatum liegt in gesperrtem/abgerechnetem Zeitraum.", "danger")
            return redirect(url_for("admin.absenz_edit", aid=aid))
        typ = (request.form.get("typ") or "Sonstiges").strip() or "Sonstiges"
        typ = typ if typ in ABSENZ_TYPEN else "Sonstiges"
        # erst prüfen, dann gesammelt zuweisen (sonst kollidiert der Unique-Constraint beim Autoflush)
        clash = Abwesenheit.query.filter(
            Abwesenheit.user_id == a.user_id,
            Abwesenheit.datum == new_datum,
            Abwesenheit.quelle == a.quelle,
            Abwesenheit.typ == typ,
            Abwesenheit.id != a.id,
        ).first()
        if clash:
            flash("An diesem Tag existiert bereits eine Abwesenheit mit gleichem Typ.", "warning")
            return redirect(url_for("admin.absenz_edit", aid=aid))
        a.datum = new_datum
        a.typ = typ
        a.bemerkung = (request.form.get("bemerkung") or "").strip() or None
        db.session.commit()
        flash("Abwesenheit gespeichert.", "success")
        return redirect(url_for("admin.absenzen", user_id=a.user_id, jahr=a.datum.year, monat=a.datum.month))
    return render_template(
        "admin/absenz_form.html", users=[a.user], absenz=a, typen=ABSENZ_TYPEN, preselect=a.user_id, today=None
    )


@bp.route("/absenzen/<int:aid>/delete", methods=["POST"])
@login_required
@chef_required
def absenz_delete(aid):
    a = db.session.get(Abwesenheit, aid)
    if a is None:
        abort(404)
    if _period_locked(a.datum):
        flash("Zeitraum gesperrt/abgerechnet — Löschung nicht möglich.", "danger")
    else:
        jahr, monat, user_id = a.datum.year, a.datum.month, a.user_id
        db.session.delete(a)
        db.session.commit()
        flash("Abwesenheit gelöscht.", "success")
        return redirect(url_for("admin.absenzen", user_id=user_id, jahr=jahr, monat=monat))
    return redirect(url_for("admin.absenzen", jahr=a.datum.year, monat=a.datum.month))


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
    "datev_lohnart_urlaub_auszahlung",
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
