"""utils/email_service.py — HTML email templates for Property Listing System."""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()


def _send(to_emails: list | str, subject: str, html: str) -> dict:
    sender   = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    if not sender or not password:
        return {"success": False, "message": "Email not configured — skipping send."}
    if isinstance(to_emails, str):
        to_emails = [e.strip() for e in to_emails.split(",") if e.strip()]
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"PropTech Realty AI <{sender}>"
        msg["To"]      = ", ".join(to_emails)
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(sender, password)
            s.sendmail(sender, to_emails, msg.as_string())
        return {"success": True, "message": f"Email sent to {', '.join(to_emails)}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def _fmt_price(p) -> str:
    try:
        v = float(p)
        if v >= 10_000_000:
            return f"₹{v/10_000_000:.2f} Cr"
        elif v >= 100_000:
            return f"₹{v/100_000:.1f} L"
        return f"₹{v:,.0f}"
    except Exception:
        return str(p)


def _wrap(content: str, badge: str, badge_color: str = "#1B4F72") -> str:
    return f"""
<div style="font-family:Arial,sans-serif;background:#0d1117;padding:28px;max-width:640px;margin:auto;border-radius:12px">
  <div style="background:linear-gradient(135deg,#1a2e4a,#1b4f72);padding:22px;border-radius:8px;text-align:center;margin-bottom:16px">
    <h2 style="color:#fff;margin:0;font-size:20px">🏠 PropTech Realty AI — Property System</h2>
    <span style="background:{badge_color};color:#fff;padding:4px 18px;border-radius:20px;font-size:12px;margin-top:8px;display:inline-block;font-weight:600">{badge}</span>
  </div>
  <div style="background:#161b22;padding:22px;border-radius:8px;color:#e2e8f0;line-height:1.8">{content}</div>
  <p style="color:#475569;font-size:11px;text-align:center;margin-top:12px">PropTech Realty AI. Contact admin@realty.com for queries.</p>
</div>"""


def _row(label, value, highlight=False):
    c = "#fbbf24" if highlight else "#e2e8f0"
    return (f'<tr><td style="padding:8px 10px;color:#94a3b8;border-bottom:1px solid #21262d;width:40%">{label}</td>'
            f'<td style="padding:8px 10px;color:{c};font-weight:{"700" if highlight else "400"};border-bottom:1px solid #21262d">{value}</td></tr>')


def send_new_listing_alert(to_email: str, buyer_name: str, listing_id: str,
                           address: str, price, bedrooms: int, city: str) -> dict:
    c = f"""<p>Dear <b>{buyer_name}</b>,</p>
<p>A new property matching your saved search has just been listed!</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Listing ID", listing_id, True)}
  {_row("Address", address)}
  {_row("City", city)}
  {_row("Price", _fmt_price(price), True)}
  {_row("Bedrooms", bedrooms)}
</table>
<p>Contact your agent to schedule a viewing today before it's gone!</p>"""
    return _send(to_email, f"🏠 New Listing Alert — {address}", _wrap(c, "NEW LISTING", "#145A32"))


def send_viewing_confirmation(buyer_email: str, agent_email: str, buyer_name: str,
                              address: str, scheduled_at: str) -> dict:
    c = f"""<p>Dear <b>{buyer_name}</b>,</p>
<p>Your property viewing has been confirmed.</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Property", address)}
  {_row("Date & Time", scheduled_at, True)}
  {_row("Agent", agent_email)}
  {_row("Status", "✅ Confirmed")}
</table>
<p style="color:#94a3b8;font-size:13px">Please arrive 5 minutes early. Contact your agent if you need to reschedule.</p>"""
    r1 = _send(buyer_email, f"📅 Viewing Confirmed — {address}", _wrap(c, "VIEWING CONFIRMED", "#1B4F72"))
    # Notify agent
    ac = f"""<p>Dear Agent,</p><p>A new viewing has been booked.</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Buyer", buyer_name)}
  {_row("Buyer Email", buyer_email)}
  {_row("Property", address)}
  {_row("Time", scheduled_at, True)}
</table>"""
    _send(agent_email, f"📅 New Viewing Booked — {address}", _wrap(ac, "VIEWING BOOKED", "#1B4F72"))
    return r1


def send_viewing_reminder(to_email: str, buyer_name: str, address: str, scheduled_at: str) -> dict:
    c = f"""<p>Dear <b>{buyer_name}</b>,</p>
<p>⏰ Reminder: You have a property viewing tomorrow!</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Property", address)}
  {_row("Time", scheduled_at, True)}
</table>
<p style="color:#94a3b8;font-size:13px">Reply to this email or contact your agent to reschedule.</p>"""
    return _send(to_email, f"⏰ Viewing Reminder Tomorrow — {address}", _wrap(c, "REMINDER", "#7D6608"))


def send_offer_status_email(buyer_email: str, seller_email: str, buyer_name: str,
                            address: str, offer_amount, status: str,
                            counter_amount=None) -> dict:
    icon = {"accepted": "✅", "rejected": "❌", "countered": "🔄", "pending": "⏳"}.get(status, "📋")
    badge_color = {"accepted": "#145A32", "rejected": "#922B21", "countered": "#7D6608", "pending": "#1B4F72"}.get(status, "#1B4F72")
    counter_row = _row("Counter Offer", _fmt_price(counter_amount), True) if counter_amount else ""
    c = f"""<p>Dear <b>{buyer_name}</b>,</p>
<p>There is an update on your offer for the following property.</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Property", address)}
  {_row("Your Offer", _fmt_price(offer_amount))}
  {_row("Status", f"{icon} {status.upper()}", True)}
  {counter_row}
</table>
<p style="color:#94a3b8;font-size:13px">Contact your agent for next steps.</p>"""
    r1 = _send(buyer_email, f"{icon} Offer {status.title()} — {address}", _wrap(c, f"OFFER {status.upper()}", badge_color))
    _send(seller_email, f"{icon} Offer Update on Your Property — {address}", _wrap(c, f"OFFER {status.upper()}", badge_color))
    return r1


def send_document_request(to_email: str, requester_name: str, doc_type: str,
                          property_address: str) -> dict:
    c = f"""<p>Dear Client,</p>
<p>The following document is required to proceed with your transaction.</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Document Required", doc_type, True)}
  {_row("Property", property_address)}
  {_row("Requested By", requester_name)}
  {_row("Action Required", "Please submit within 5 business days")}
</table>
<p style="color:#94a3b8;font-size:13px">Failure to provide documents on time may delay or cancel the transaction.</p>"""
    return _send(to_email, f"📄 Document Required: {doc_type}", _wrap(c, "DOCUMENT REQUEST", "#512E5F"))


def send_contract_email(to_emails: str, party_name: str, contract_type: str,
                        property_address: str) -> dict:
    c = f"""<p>Dear <b>{party_name}</b>,</p>
<p>Please find your {contract_type} ready for review.</p>
<table width="100%" style="border-collapse:collapse;margin:12px 0;background:#0d1117;border-radius:6px">
  {_row("Document", contract_type, True)}
  {_row("Property", property_address)}
  {_row("Action", "Please review, sign, and return within 48 hours")}
</table>
<p style="color:#94a3b8;font-size:13px">Contact your agent or legal representative with any questions.</p>"""
    return _send(to_emails, f"📑 Contract Ready: {contract_type} — {property_address}", _wrap(c, "CONTRACT", "#1B4F72"))


def send_market_report_email(to_email: str, recipient_name: str,
                             city: str, report_summary: str) -> dict:
    c = f"""<p>Dear <b>{recipient_name}</b>,</p>
<p>Your market report for <b>{city}</b> is ready.</p>
<div style="background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:14px;margin:12px 0">
  <pre style="color:#e2e8f0;font-size:13px;white-space:pre-wrap">{report_summary[:800]}</pre>
</div>
<p style="color:#94a3b8;font-size:13px">Contact your broker for investment advice based on this report.</p>"""
    return _send(to_email, f"📊 Market Report — {city}", _wrap(c, "MARKET REPORT", "#0E6655"))


def send_followup_email(to_email: str, client_name: str, agent_name: str,
                        message: str, properties: list = None) -> dict:
    prop_html = ""
    if properties:
        rows = "".join([f'<tr><td style="padding:6px 10px;color:#e2e8f0;border-bottom:1px solid #21262d">{p}</td></tr>' for p in properties[:3]])
        prop_html = f'<p><b>Recommended Properties:</b></p><table width="100%" style="border-collapse:collapse;background:#0d1117;border-radius:6px">{rows}</table>'
    c = f"""<p>Dear <b>{client_name}</b>,</p>
<p>{message}</p>
{prop_html}
<p style="color:#94a3b8;font-size:13px">Regards,<br><b>{agent_name}</b> — PropTech Realty AI</p>"""
    return _send(to_email, f"🏠 Follow-up from {agent_name}", _wrap(c, "FOLLOW-UP", "#1B4F72"))