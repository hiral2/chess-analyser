"""SMTP delivery of the generated PDF report."""
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_report_email(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    email_from: str,
    email_to: str,
    subject: str,
    body: str,
    pdf_path: str,
) -> None:
    recipients = [addr.strip() for addr in email_to.split(",") if addr.strip()]
    if not recipients:
        raise ValueError("No recipients configured (EMAIL_TO is empty)")

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(pdf_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=pdf_path.split("/")[-1])
        msg.attach(attachment)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        if smtp_username and smtp_password:
            server.login(smtp_username, smtp_password)
        server.sendmail(email_from, recipients, msg.as_string())
