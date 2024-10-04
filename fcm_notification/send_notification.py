import frappe
import json
from frappe import enqueue
import re
import firebase_admin
from firebase_admin import credentials, messaging


def user_id(doc):
    user_email = doc.for_user
    user_device_id = frappe.get_all(
        "User Device", filters={"user": user_email}, fields=["device_id"]
    )
    return user_device_id


@frappe.whitelist()
def send_notification(doc, event=None):
    device_ids = user_id(doc)
    for device_id in device_ids:
        enqueue(
            process_notification,
            queue="default",
            now=False,
            device_id=device_id,
            notification=doc,
        )


def convert_message(message):
    CLEANR = re.compile("<.*?>")
    cleanmessage = re.sub(CLEANR, "", message)
    # cleantitle = re.sub(CLEANR, "",title)
    return cleanmessage

def firebase_app():
    server_key = frappe.db.get_single_value("FCM Notification Settings", "server_key")
    cred = credentials.Certificate(json.loads(server_key))
    app = firebase_admin.initialize_app(cred)

def process_notification(device_id, notification):
    firebase_app()
    fcm_token = get_user_fcm_token_by_email(notification.for_user)
    message = notification.email_content
    data = {
        "document_name": notification.document_name,
        "document_type": notification.document_type,
        "for_user": notification.for_user,
        "from_user": notification.owner
    }
    if notification.owner != notification.for_user:
        name = get_doc_owner_name(notification.owner)
        message = f"{name} has {message[9:]}"
    if fcm_token:
        send_push_notification(fcm_token, notification.subject, message, data)


def get_user_fcm_token_by_email(email):
    fcm_token = frappe.db.get_value("Employee", {"user_id": email}, ["custom_fcm_token"])
    return fcm_token

def get_doc_owner_name(email):
    name = frappe.db.get_value("Employee", {"user_id": email}, ["employee_name"])
    return name

def send_push_notification(fcm_token, title, body, data=None):
    notification = messaging.Notification(title=title, body=body)
    message = messaging.Message(notification=notification, token=fcm_token, data=data)
    messaging.send(message)
