"""Scholens Project invitation email composition."""

from __future__ import annotations

import html
from urllib.parse import quote, urlsplit

from app.modules.notifications.application import TransactionalEmailMessage


def _public_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CLIENT_DOMAIN must be an absolute HTTP(S) URL")
    return base


def build_project_invitation_email(
    *,
    inviter_name: str,
    project_title: str,
    invitation_token: str,
    client_domain: str,
) -> TransactionalEmailMessage:
    """Build equivalent HTML and text bodies without interpolating unsafe markup."""
    base = _public_base_url(client_domain)
    action_url = f"{base}/project-invitations/{quote(invitation_token, safe='.-_~')}"
    safe_url = html.escape(action_url, quote=True)
    inviter = (
        inviter_name.replace("\r", " ").replace("\n", " ").strip()[:160]
        or "A Scholens collaborator"
    )
    title = project_title.strip()[:240] or "Untitled project"
    safe_inviter = html.escape(inviter, quote=True)
    safe_title = html.escape(title, quote=True)
    subject = f"{inviter} invited you to a Scholens project"
    html_body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f7f7f4;color:#171713;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">Join {safe_title} on Scholens.</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
         style="width:100%;background:#f7f7f4;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
             style="width:100%;max-width:600px;background:#fff;border:1px solid #deded7;">
        <tr><td style="padding:32px 38px 12px;font-family:Georgia,serif;font-size:24px;font-weight:700;">Scholens</td></tr>
        <tr><td style="padding:18px 38px 8px;font-family:Arial,sans-serif;color:#68685f;font-size:12px;font-weight:700;letter-spacing:.06em;">PROJECT INVITATION</td></tr>
        <tr><td style="padding:0 38px;font-family:Georgia,serif;font-size:28px;font-weight:700;line-height:1.3;">{safe_title}</td></tr>
        <tr><td style="padding:20px 38px 0;font-family:Arial,sans-serif;font-size:15px;line-height:1.65;color:#505048;">{safe_inviter} invited you to collaborate on this project.</td></tr>
        <tr><td style="padding:26px 38px 30px;"><a href="{safe_url}" style="display:inline-block;padding:13px 22px;border-radius:6px;background:#24241f;color:#fff;font-family:Arial,sans-serif;font-size:14px;font-weight:700;text-decoration:none;">Review invitation</a></td></tr>
        <tr><td style="padding:20px 38px 28px;background:#f1f1ec;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;color:#68685f;">This invitation expires in 7 days. If the button does not work, open:<br><a href="{safe_url}" style="color:#33332d;word-break:break-all;">{safe_url}</a></td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
    text_body = (
        "Scholens\n\nPROJECT INVITATION\n"
        f"{title}\n\n{inviter} invited you to collaborate on this project.\n\n"
        f"Review invitation: {action_url}\n\nThis invitation expires in 7 days."
    )
    return TransactionalEmailMessage(
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )


__all__ = ["build_project_invitation_email"]
