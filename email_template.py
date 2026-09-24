"""Notification email for "Book a pilot" requests, styled like the landing page.

Email clients ignore <style> blocks and web fonts unevenly, so everything is
table-based with inline styles and system font stacks.
"""
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import quote, urlsplit

BG = "#07090C"
CARD = "#0D1015"
LINE = "#1C2129"
TEXT = "#EEF1F4"
MUTED = "#A7B0BB"
DIM = "#8C96A2"
AMBER = "#F2B544"
CYAN = "#5CCFE6"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'SFMono-Regular',Menlo,Consolas,'Liberation Mono',monospace"
ICT = timezone(timedelta(hours=7), "ICT")


def _when(now):
    local = now.astimezone(ICT)
    return f"{local:%d %b %Y · %H:%M} ICT", f"{now.astimezone(timezone.utc):%H:%M} UTC"


def _short_page(page):
    if not page:
        return "-"
    u = urlsplit(page)
    return (u.netloc + u.path) or page


def _browser(agent):
    a = agent or ""
    for name, key in (("Edge", "Edg/"), ("Chrome", "Chrome/"), ("Firefox", "Firefox/"), ("Safari", "Safari/")):
        if key in a:
            break
    else:
        name = "Unknown browser"
    for osname, key in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("macOS", "Mac OS X"), ("Windows", "Windows"), ("Linux", "Linux")):
        if key in a:
            return f"{name} · {osname}"
    return name


def subject(email):
    return f"New pilot request · {email}"


def plain_text(email, page, ip, agent, now=None):
    now = now or datetime.now(timezone.utc)
    local, utc = _when(now)
    return (
        "NEW PILOT REQUEST — SpartansE-V\n\n"
        "Someone wants to run a 60-day pilot.\n\n"
        f"Contact:   {email}\n"
        f"Received:  {local} ({utc})\n"
        f"Source:    {_short_page(page)}\n"
        f"Browser:   {_browser(agent)}\n"
        f"IP:        {ip}\n\n"
        "Reply to this email to answer them directly — aim for one business day.\n"
    )


def html(email, page, ip, agent, now=None):
    now = now or datetime.now(timezone.utc)
    local, utc = _when(now)
    e = escape(email, quote=True)
    reply = "mailto:" + quote(email, safe="@") + "?subject=" + quote("Your SpartansE-V pilot request")

    def row(label, value, last=False):
        border = "" if last else f"border-bottom:1px solid {LINE};"
        return (
            f'<tr><td style="{border}padding:14px 0;font:500 11px/1.4 {MONO};letter-spacing:.08em;color:{DIM};width:112px;vertical-align:top">{label}</td>'
            f'<td style="{border}padding:14px 0;font:400 14px/1.5 {SANS};color:{TEXT};vertical-align:top">{value}</td></tr>'
        )

    details = "".join([
        row("RECEIVED", f'{escape(local)} <span style="color:{DIM}">· {escape(utc)}</span>'),
        row("SOURCE", escape(_short_page(page))),
        row("BROWSER", escape(_browser(agent))),
        row("IP", f'<span style="font-family:{MONO};font-size:13px">{escape(ip)}</span>', last=True),
    ])

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">
<title>{escape(subject(email))}</title></head>
<body style="margin:0;padding:0;background:{BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG}">{e} wants to book a 60-day pilot — reply within one business day.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BG};">
<tr><td align="center" style="padding:40px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;">

  <!-- brand -->
  <tr><td style="padding:0 4px 24px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="vertical-align:middle;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td style="width:22px;height:22px;border:2px solid {AMBER};border-radius:50%;text-align:center;vertical-align:middle;line-height:0;">
            <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{AMBER};"></span>
          </td>
          <td style="padding-left:10px;font:600 16px/1 {SANS};color:{TEXT};letter-spacing:-.01em;">SpartansE-V</td>
        </tr></table>
      </td>
      <td align="right" style="font:500 11px/1 {MONO};letter-spacing:.12em;color:{DIM};">TIRE INTELLIGENCE</td>
    </tr></table>
  </td></tr>

  <!-- main card -->
  <tr><td style="background:{CARD};border:1px solid {LINE};border-radius:20px;overflow:hidden;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr><td style="height:3px;line-height:3px;font-size:0;background:{AMBER};border-radius:20px 20px 0 0;">&nbsp;</td></tr>
      <tr><td style="padding:36px 36px 8px;">
        <div style="font:500 12px/1 {MONO};letter-spacing:.12em;color:{AMBER};">&#9679;&nbsp; NEW PILOT REQUEST</div>
        <h1 style="margin:16px 0 0;font:600 30px/1.1 {SANS};letter-spacing:-.03em;color:{TEXT};">Someone wants to <span style="color:{AMBER};">book a pilot.</span></h1>
        <p style="margin:14px 0 0;font:400 16px/1.6 {SANS};color:{MUTED};">A visitor on the landing page asked to run a 60-day pilot with their own inspection history. Reply within one business day to keep the momentum.</p>
      </td></tr>

      <!-- contact -->
      <tr><td style="padding:24px 36px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#10141A;border:1px solid {LINE};border-radius:14px;">
          <tr><td style="padding:20px 22px;">
            <div style="font:500 11px/1 {MONO};letter-spacing:.08em;color:{DIM};">CONTACT</div>
            <div style="margin-top:10px;font:600 20px/1.3 {SANS};letter-spacing:-.01em;word-break:break-all;">
              <a href="mailto:{e}" style="color:{TEXT};text-decoration:none;border-bottom:1px solid {AMBER};">{e}</a>
            </div>
          </td></tr>
        </table>
      </td></tr>

      <!-- actions -->
      <tr><td style="padding:24px 36px 8px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td style="background:{AMBER};border-radius:999px;">
            <a href="{escape(reply, quote=True)}" style="display:inline-block;padding:14px 26px;font:600 15px/1 {SANS};color:#0A0C10;text-decoration:none;">Reply to request &rarr;</a>
          </td>
        </tr></table>
      </td></tr>

      <!-- details -->
      <tr><td style="padding:20px 36px 32px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid {LINE};">
          {details}
        </table>
      </td></tr>
    </table>
  </td></tr>

  <!-- hint -->
  <tr><td style="padding:20px 4px 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="width:3px;background:{CYAN};border-radius:3px;"></td>
      <td style="padding:2px 0 2px 14px;font:400 13px/1.55 {SANS};color:{MUTED};">
        Hitting <strong style="color:{TEXT};font-weight:600;">Reply</strong> in your mail app also works — this email's Reply-To is set to the visitor.
      </td>
    </tr></table>
  </td></tr>

  <!-- footer -->
  <tr><td style="padding:32px 4px 0;font:400 12px/1.6 {SANS};color:{DIM};">
    Sent automatically by the SpartansE-V landing page.<br>
    Decision support within AMM limits · &copy; {now.year} SpartansE-V
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""


if __name__ == "__main__":
    # python3 email_template.py > email-preview.html
    print(html("ops.planning@airline.example", "https://spartanse-v.example/", "203.0.113.42",
               "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15"))
