from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import TimeEntry, Urlaubsantrag
from .utils import (
    entries_in_period,
    fmt_hhmm,
    get_or_create_period,
    ist_minuten,
    parse_time,
    period_for,
    saldo_minuten,
    soll_minuten,
    urlaubskonto,
    workdays_between,
)

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    now = datetime.now()
    period = get_or_create_period(now)
    running = (
        TimeEntry.query.filter_by(user_id=current_user.id, ende=None)
        .order_by(TimeEntry.start.desc())
        .first()
    )
    entries = entries_in_period(current_user.id, period)
    konto = urlaubskonto(current_user, now.year)
    antraege = (
        Urlaubsantrag.query.filter_by(user_id=current_user.id)
        .order_by(Urlaubsantrag.von.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "dashboard.html",
        period=period,
        running=running,
        entries=entries,
        ist=ist_minuten(current_user.id, period),
        soll=soll_minuten(current_user, period),
        saldo=saldo_minuten(current_user, period),
        konto=konto,
        antraege=antraege,
        fmt_hhmm=fmt_hhmm,
        now=now,
    )


@bp.route("/start", methods=["POST"])
@login_required
def start_timer():
    running = TimeEntry.query.filter_by(user_id=current_user.id, ende=None).first()
    if running:
        flash("Es läuft bereits eine Buchung.", "info")
    else:
        kategorie = (request.form.get("kategorie") or "Allgemein").strip() or "Allgemein"
        entry = TimeEntry(
            user_id=current_user.id,
            start=datetime.now(),
            ende=None,
            dauer_minuten=None,
            kategorie=kategorie,
            quelle="manuell",
        )
        db.session.add(entry)
        db.session.commit()
        flash("Buchung gestartet.", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/entries/<int:entry_id>/stop", methods=["POST"])
@login_required
def stop_entry(entry_id):
    entry = db.session.get(TimeEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        abort(404)
    if entry.ende is None:
        entry.ende = datetime.now()
        entry.dauer_minuten = int((entry.ende - entry.start).total_seconds() // 60)
        db.session.commit()
        flash("Buchung gestoppt.", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/entries", methods=["GET", "POST"])
@login_required
def entries():
    now = datetime.now()
    jahr = int(request.args.get("jahr", now.year) or now.year)
    monat = int(request.args.get("monat", now.month) or now.month)
    period = period_for(jahr, monat) or get_or_create_period(datetime(jahr, monat, 1))

    if request.method == "POST":
        datum_s = request.form.get("datum", "")
        von_s = request.form.get("von", "")
        bis_s = request.form.get("bis", "")
        kategorie = (request.form.get("kategorie") or "Allgemein").strip() or "Allgemein"
        bemerkung = (request.form.get("bemerkung") or "").strip() or None
        try:
            d = datetime.strptime(datum_s, "%Y-%m-%d").date()
        except ValueError:
            flash("Ungültiges Datum.", "danger")
            return redirect(url_for("main.entries", jahr=jahr, monat=monat))
        von = parse_time(von_s)
        bis = parse_time(bis_s)
        if von is None or bis is None:
            flash("Ungültige Uhrzeit (Format HH:MM).", "danger")
            return redirect(url_for("main.entries", jahr=jahr, monat=monat))
        start = datetime.combine(d, von)
        ende = datetime.combine(d, bis)
        if ende <= start:
            ende += timedelta(days=1)
        p = period_for(start.year, start.month)
        if p and p.gesperrt:
            flash(f"Zeitraum {p.name} ist gesperrt — Buchung nicht möglich.", "danger")
            return redirect(url_for("main.entries", jahr=jahr, monat=monat))
        entry = TimeEntry(
            user_id=current_user.id,
            start=start,
            ende=ende,
            dauer_minuten=int((ende - start).total_seconds() // 60),
            kategorie=kategorie,
            bemerkung=bemerkung,
            quelle="manuell",
        )
        db.session.add(entry)
        db.session.commit()
        flash("Buchung gespeichert.", "success")
        return redirect(url_for("main.entries", jahr=start.year, monat=start.month))

    entries_list = entries_in_period(current_user.id, period)
    return render_template(
        "entries.html",
        period=period,
        entries=entries_list,
        fmt_hhmm=fmt_hhmm,
        jahr=jahr,
        monat=monat,
    )


@bp.route("/entries/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_entry(entry_id):
    entry = db.session.get(TimeEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        abort(404)
    p = period_for(entry.start.year, entry.start.month)
    if p and p.gesperrt:
        flash("Zeitraum gesperrt — Löschen nicht möglich.", "danger")
        return redirect(url_for("main.entries"))
    jahr, monat = entry.start.year, entry.start.month
    db.session.delete(entry)
    db.session.commit()
    flash("Buchung gelöscht.", "info")
    return redirect(url_for("main.entries", jahr=jahr, monat=monat))


@bp.route("/urlaub", methods=["GET", "POST"])
@login_required
def urlaub():
    now = datetime.now()
    if request.method == "POST":
        von_s = request.form.get("von", "")
        bis_s = request.form.get("bis", "")
        bemerkung = (request.form.get("bemerkung") or "").strip() or None
        try:
            von = datetime.strptime(von_s, "%Y-%m-%d").date()
            bis = datetime.strptime(bis_s, "%Y-%m-%d").date()
        except ValueError:
            flash("Ungültiges Datum.", "danger")
            return redirect(url_for("main.urlaub"))
        if bis < von:
            flash("Bis-Datum liegt vor Von-Datum.", "danger")
            return redirect(url_for("main.urlaub"))
        tage = workdays_between(von, bis)
        antrag = Urlaubsantrag(
            user_id=current_user.id, von=von, bis=bis, tage=tage, bemerkung=bemerkung, status="beantragt"
        )
        db.session.add(antrag)
        db.session.commit()
        flash(f"Urlaubsantrag über {tage} Arbeitstag(e) gestellt.", "success")
        return redirect(url_for("main.urlaub"))
    antraege = (
        Urlaubsantrag.query.filter_by(user_id=current_user.id)
        .order_by(Urlaubsantrag.von.desc())
        .all()
    )
    konto = urlaubskonto(current_user, now.year)
    return render_template("urlaub.html", antraege=antraege, konto=konto, now=now)
