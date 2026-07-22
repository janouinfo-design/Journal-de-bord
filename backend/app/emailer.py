"""Envoi d'emails via le serveur SMTP du client (configuré en .env, optionnel).

Si SMTP_HOST/SMTP_FROM ne sont pas configurés, l'application retombe sur
l'affichage du lien d'invitation à copier manuellement.
"""
import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _send_sync(to: str, subject: str, text: str, html: str):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT") or 587)
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    msg = EmailMessage()
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if port == 465:  # TLS implicite (SMTPS)
        with smtplib.SMTP_SSL(host, port, timeout=20) as s:
            if user and password:
                s.login(user, password)
            s.send_message(msg)
    else:  # STARTTLS (587) ou clair (25) si non supporté
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            try:
                s.starttls()
                s.ehlo()
            except smtplib.SMTPNotSupportedError:
                logger.warning("SMTP: STARTTLS non supporté par %s:%s — envoi non chiffré", host, port)
            if user and password:
                s.login(user, password)
            s.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str) -> bool:
    try:
        await asyncio.to_thread(_send_sync, to, subject, text, html)
        logger.info("SMTP: email envoyé à %s (%s)", to, subject)
        return True
    except Exception as e:
        logger.error("SMTP: échec d'envoi à %s: %s", to, e)
        return False


async def send_test_email(to: str):
    """Envoi synchrone d'un email de test — propage l'exception SMTP pour diagnostic."""
    subject = "Test SMTP — Journal de bord Logitrak"
    text = (
        "Ceci est un email de test envoyé depuis le Journal de bord Logitrak.\n"
        "Votre configuration SMTP fonctionne correctement.\n"
    )
    html = """\
<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;background:#f4f6f8;padding:24px;">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:8px;padding:32px;border:1px solid #e2e8f0;">
    <h2 style="margin:0 0 8px;color:#0f172a;">✓ Test SMTP réussi</h2>
    <p style="color:#334155;">Ceci est un email de test envoyé depuis le <strong>Journal de bord Logitrak</strong>.</p>
    <p style="color:#334155;">Votre configuration SMTP fonctionne correctement — les invitations chauffeur
       et les futurs rappels par email seront bien délivrés.</p>
  </div>
</body></html>"""
    await asyncio.to_thread(_send_sync, to, subject, text, html)


async def send_invitation_email(to: str, driver_name: str, invite_url: str, company: str):
    subject = f"Invitation — Journal de bord {company}"
    text = (
        f"Bonjour {driver_name},\n\n"
        f"Vous êtes invité(e) à activer votre accès au Journal de bord de {company}.\n"
        f"Cliquez sur ce lien pour créer votre mot de passe :\n\n{invite_url}\n\n"
        "Ce lien est valable 7 jours et ne peut être utilisé qu'une seule fois.\n"
    )
    html = f"""\
<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;background:#f4f6f8;padding:24px;">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:8px;padding:32px;border:1px solid #e2e8f0;">
    <h2 style="margin:0 0 8px;color:#0f172a;">Journal de bord — {company}</h2>
    <p style="color:#334155;">Bonjour <strong>{driver_name}</strong>,</p>
    <p style="color:#334155;">Vous êtes invité(e) à activer votre accès chauffeur au Journal de bord.
       Cliquez sur le bouton ci-dessous pour créer votre mot de passe :</p>
    <p style="text-align:center;margin:28px 0;">
      <a href="{invite_url}" style="display:inline-block;padding:12px 24px;background:#2196F3;color:#ffffff;
         text-decoration:none;border-radius:6px;font-weight:bold;">Créer mon mot de passe</a>
    </p>
    <p style="color:#64748b;font-size:13px;">Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :<br>
      <a href="{invite_url}" style="color:#2196F3;word-break:break-all;">{invite_url}</a></p>
    <p style="color:#94a3b8;font-size:12px;">Ce lien est valable 7 jours et ne peut être utilisé qu'une seule fois.</p>
  </div>
</body></html>"""
    return await send_email(to, subject, text, html)
