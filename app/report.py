"""Monatsbericht als PDF (fpdf2, Core-Fonts latin-1 - Umlaute sind enthalten)."""

from fpdf import FPDF

from .utils import fmt_hhmm, urlaub_modus, urlaubauszahlung_stunden


def _latin1(s):
    return str(s).encode("latin-1", "replace").decode("latin-1")


def build_monthly_pdf(user, period, entries, absenzen, ist, soll, saldo, urlaubskonto) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, _latin1(f"Monatsbericht {period.name}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 11)
    pdf.cell(0, 7, _latin1(f"Mitarbeiter: {user.name}  (Personalnummer: {user.personalnummer or '-'})"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, _latin1(f"Abteilung: {user.department or '-'}    Zeitraum: {period.name} ({period.status})"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Buchungen
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Zeitbuchungen", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "B", 9)
    widths = [22, 16, 16, 18, 40, 24, 54]
    headers = ["Datum", "Von", "Bis", "Dauer", "Kategorie", "Quelle", "Bemerkung"]
    for w, h in zip(widths, headers):
        pdf.cell(w, 7, _latin1(h), border=1)
    pdf.ln()
    pdf.set_font("helvetica", "", 9)
    for en in entries:
        row = [
            en.start.strftime("%d.%m.%Y"),
            en.start.strftime("%H:%M"),
            en.ende.strftime("%H:%M") if en.ende else "läuft",
            fmt_hhmm(en.dauer),
            en.kategorie,
            en.quelle,
            (en.bemerkung or "")[:30],
        ]
        for w, v in zip(widths, row):
            pdf.cell(w, 6, _latin1(v), border=1)
        pdf.ln()
    pdf.ln(3)

    # Summen
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Zeitkonto", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 11)
    pdf.cell(0, 7, _latin1(f"Ist: {fmt_hhmm(ist)} h   |   Soll: {fmt_hhmm(soll)} h   |   Saldo/Gleitzeit: {fmt_hhmm(saldo)} h"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Abwesenheiten
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Abwesenheiten", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    if absenzen:
        for a in absenzen:
            pdf.cell(0, 6, _latin1(f"{a.datum:%d.%m.%Y}  -  {a.typ}" + (f"  ({a.bemerkung})" if a.bemerkung else "")), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "- keine -", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Urlaub: Modus 'auszahlung' -> Zwölftel der Monatsstunden, Konto wird nicht belastet
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, f"Urlaub {urlaubskonto['jahr']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 11)
    if urlaub_modus(user) == "auszahlung":
        payout = urlaubauszahlung_stunden(ist)
        pdf.cell(0, 7, _latin1(f"Modus: Auszahlung - Zwölftel der Monatsstunden = {payout:.2f} h"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, _latin1("Urlaubskonto wird in diesem Modus nicht belastet."), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 7, _latin1(f"Anspruch: {urlaubskonto['anspruch']} Tage  |  genommen: {urlaubskonto['genommen']}  |  Rest: {urlaubskonto['rest']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, _latin1(f"Urlaubsstunden pro Tag: {getattr(user, 'urlaub_stunden_pro_tag', 8.0)} h"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("helvetica", "I", 8)
    pdf.ln(6)
    pdf.cell(0, 5, _latin1("Erzeugt durch Zeiterfassung Weidenhof - ohne Gewähr."), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
