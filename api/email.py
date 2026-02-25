"""Email handling for Concierge — receive, process, and reply via SES."""

import email
import json
import logging
from email import policy as email_policy
from typing import Optional

import boto3
import requests

from .config import config
from . import memory
from .sonnet import chat

logger = logging.getLogger(__name__)

SES_REGION = "eu-west-1"
S3_BUCKET = "concierge-mail-monce"
SENDER = "concierge@aws.monce.ai"

SIGNATURE = """
---
Moncey Concierge
Monce AI — Memory & Intelligence Layer
https://concierge.aws.monce.ai
"""


def _get_ses_client():
    """Get SES client for eu-west-1."""
    return boto3.client(
        "ses",
        region_name=SES_REGION,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )


def _get_s3_client():
    """Get S3 client for email bucket."""
    return boto3.client(
        "s3",
        region_name=SES_REGION,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )


def parse_email_from_s3(message_id: str) -> dict:
    """Fetch raw email from S3 and parse it."""
    s3 = _get_s3_client()

    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"incoming/{message_id}")
        raw = obj["Body"].read()
    except Exception as e:
        logger.error(f"Failed to fetch email {message_id} from S3: {e}")
        raise

    msg = email.message_from_bytes(raw, policy=email_policy.default)

    # Extract text body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
            elif part.get_content_type() == "text/html" and not body:
                body = part.get_content()
    else:
        body = msg.get_content()

    return {
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "body": body.strip() if body else "",
        "date": msg.get("Date", ""),
        "message_id": msg.get("Message-ID", ""),
    }


def process_sns_notification(body: dict) -> Optional[dict]:
    """Process an SNS notification from SES.

    Handles:
    - SubscriptionConfirmation: auto-confirms
    - Notification: processes email
    """
    msg_type = body.get("Type", "")

    if msg_type == "SubscriptionConfirmation":
        subscribe_url = body.get("SubscribeURL")
        if subscribe_url:
            logger.info(f"Confirming SNS subscription: {subscribe_url}")
            requests.get(subscribe_url, timeout=10)
            return {"confirmed": True}

    if msg_type == "Notification":
        message = json.loads(body.get("Message", "{}"))
        receipt = message.get("receipt", {})
        mail = message.get("mail", {})

        # Get message details from SES notification
        source = mail.get("source", "unknown")
        subject = mail.get("commonHeaders", {}).get("subject", "No subject")
        message_id = mail.get("messageId", "")

        logger.info(f"Incoming email from {source}: {subject}")

        # Try to get full body from S3
        email_body = ""
        try:
            parsed = parse_email_from_s3(message_id)
            email_body = parsed["body"]
        except Exception as e:
            logger.warning(f"Could not fetch email body from S3: {e}")
            # Fall back to snippet from headers
            email_body = subject

        # Build the query for Concierge
        query = f"[Email from {source}] Subject: {subject}"
        if email_body:
            # Truncate very long emails
            body_snippet = email_body[:2000]
            query += f"\n\n{body_snippet}"

        # Store as memory
        memory.add_memory(
            f"Email received from {source} — Subject: {subject} — {email_body[:200]}",
            source="email",
            tags=["email", "incoming"],
        )

        # Get Concierge's reply
        result = chat(query)
        reply_text = result["reply"]

        # Send reply
        try:
            send_reply(
                to=source,
                subject=f"Re: {subject}",
                body=reply_text,
            )
            memory.add_memory(
                f"Email replied to {source} — Re: {subject} — {reply_text[:200]}",
                source="email",
                tags=["email", "outgoing"],
            )
        except Exception as e:
            logger.error(f"Failed to send reply to {source}: {e}")

        return {
            "from": source,
            "subject": subject,
            "reply_sent": True,
            "latency_ms": result["latency_ms"],
        }

    return None


def send_reply(to: str, subject: str, body: str):
    """Send a reply email via SES."""
    ses = _get_ses_client()

    full_body = body + SIGNATURE

    ses.send_email(
        Source=f"Moncey Concierge <{SENDER}>",
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": full_body, "Charset": "UTF-8"},
            },
        },
    )
    logger.info(f"Reply sent to {to}: {subject}")


def send_email(to: str, subject: str, body: str):
    """Send an email from Concierge (for outbound notifications)."""
    send_reply(to=to, subject=subject, body=body)
