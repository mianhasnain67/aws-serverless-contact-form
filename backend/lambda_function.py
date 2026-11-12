"""
Contact form handler (AWS Lambda, Python).

Triggered by API Gateway (HTTP API) on POST /contact.
  1. Validates the request body
  2. Saves the submission to DynamoDB
  3. Sends a confirmation email to the visitor (SES)
  4. Publishes an alert to the owner (SNS)

Required environment variables:
  TABLE_NAME      DynamoDB table name (partition key: id, String)
  SNS_TOPIC_ARN   ARN of the SNS topic that alerts the owner
  SENDER_EMAIL    SES verified sender address
"""
import json
import os
import uuid
from datetime import datetime, timezone

import boto3

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")
sns = boto3.client("sns")

TABLE_NAME = os.environ["TABLE_NAME"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
SENDER_EMAIL = os.environ["SENDER_EMAIL"]

table = dynamodb.Table(TABLE_NAME)

# CORS itself is configured on API Gateway; these headers are a fallback.
HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def response(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body)}


def lambda_handler(event, context):
    try:
        data = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return response(400, {"message": "Invalid JSON"})

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return response(400, {"message": "Name, email and message are required"})

    submission_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    # 1. Save to DynamoDB
    table.put_item(
        Item={
            "id": submission_id,
            "name": name,
            "email": email,
            "message": message,
            "createdAt": created_at,
        }
    )

    # 2. Confirmation email to the visitor (failure must not break the form)
    try:
        ses.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": "We received your message"},
                "Body": {
                    "Text": {
                        "Data": (
                            f"Hi {name},\n\n"
                            "Thank you for contacting us. We have received your "
                            "message and will get back to you soon.\n\n"
                            f"Your message:\n{message}"
                        )
                    }
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        print("SES error:", str(exc))

    # 3. Alert to the owner
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="New Contact Form Submission",
            Message=(
                f"Name: {name}\nEmail: {email}\n"
                f"Message: {message}\nTime: {created_at}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print("SNS error:", str(exc))

    return response(200, {"message": "Thank you! Your message has been received."})
