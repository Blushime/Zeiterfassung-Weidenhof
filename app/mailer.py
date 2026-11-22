"""E-Mail-Versand (SMTP) — z. B. Benachrichtigung bei neuem Urlaubsantrag.

Konfiguration über Admin → Einstellungen (Settings-Keys smtp_*). Ohne smtp_host wird
kein Versand versucht (notify_* liefern False).
"""

import smtplib
from email.message import EmailMessage

from flask import current_app

from .utils import get_setting


def smtp_configured() -> bool:
    return bool(get_setting("smtp_host"))


def send_mail(subject: str, body: str, recipients: list) -> bool:
    host = get_setting("smtp_host")
    if not host or not recipients:
        return False
    port = int(get_setting("smtp_port", "587") or 587)
    user = get_setting("smtp_user")
    password = get_setting("smtp_password")
    frm = get_setting("smtp_from") or user or "zeiterfassung@localhost"
    use_tls = get_setting("smtp_tls", "1") == "1"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as server:
        if use_tls:
            server.starttls()
        if user:
            server.login(user, password or "")
        server.send_message(msg)
    return True


def notify_urlaub_antrag(antrag) -> bool:
    """Benachrichtigt alle aktiven admin/chef per E-Mail über einen neuen Urlaubsantrag."""
    from .models import User

    if not smtp_configured():
        current_app.logger.info("SMTP nicht konfiguriert — keine E-Mail für Urlaubsantrag #%s", antrag.id)
        return False
    recipients = [
        u.email
        for u in User.query.filter(User.aktiv.is_(True), User.role.in_(["admin", "chef"])).all()
        if u.email
    ]
    if not recipients:
        return False
    subject = f"Neuer Urlaubsantrag: {antrag.user.name} ({antrag.von:%d.%m.%Y}–{antrag.bis:%d.%m.%Y})"
    body = (
        f"Hallo,\n\n"
        f"{antrag.user.name} hat einen neuen Urlaubsantrag gestellt:\n\n"
        f"  Von:        {antrag.von:%d.%m.%Y}\n"
        f"  Bis:        {antrag.bis:%d.%m.%Y}\n"
        f"  Arbeitstage: {antrag.tage}\n"
        f"  Bemerkung:  {antrag.bemerkung or '-'}\n\n"
        f"Bitte im Admin-Bereich genehmigen oder ablehnen.\n"
    )
    try:
        send_mail(subject, body, recipients)
        current_app.logger.info("Urlaubsantrag #%s per E-Mail an %s gemeldet", antrag.id, recipients)
        return True
    except Exception as e:
        current_app.logger.warning("E-Mail-Versand für Urlaubsantrag #%s fehlgeschlagen: %s", antrag.id, e)
        return False
