import frappe
import json
from frappe import enqueue
import re
import firebase_admin
from firebase_admin import credentials, messaging

frappe.utils.logger.set_log_level("DEBUG")
logger = frappe.logger("push_notification", allow_site=True, file_count=5)

def get_user_fcm_tokens(user_email):
    user_fcm_tokens = frappe.get_all(
        "User Device", filters={"user": user_email, "is_active": 1}, fields=["fcm_token"]
    )
    return user_fcm_tokens


@frappe.whitelist()
def create_or_update_user_device(device_id, device_name, device_manufacturer, fcm_token):
    user = frappe.session.user
    if frappe.db.exists("User Device", {"device_id": device_id}):
        user_device = frappe.get_doc("User Device", {"device_id": device_id})
        user_device.user = user
        user_device.device_name = device_name
        user_device.device_manufacturer = device_manufacturer
        user_device.fcm_token = fcm_token
        user_device.is_active = 1
        user_device.save()
        frappe.db.commit()
        return "User device has been updated"
    else:
        new_user_device = frappe.get_doc({
                "doctype": "User Device",
                "user": user,
                "device_name": device_name,
                "device_id": device_id,
                "device_manufacturer": device_manufacturer,
                "fcm_token": fcm_token,
                "is_active": 1
            })
        new_user_device.insert()
        frappe.db.commit()
        return "New user device has been registered"


@frappe.whitelist()
def mark_device_as_inactive():
    email = frappe.session.user
    user_device_id = frappe.get_all(
        "User Device", filters={"user": email}, fields=["device_id"]
    )
    if user_device_id:
        user_device = frappe.get_doc("User Device", {"user": email})
        user_device.is_active = 0
        user_device.save()
        frappe.db.commit()
        return "Device has been marked as inactive successfully."


@frappe.whitelist()
def send_notification(doc, event=None):
    enqueue(
        process_notification,
        queue="default",
        now=False,
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
    firebase_admin.initialize_app(cred)


def process_notification(notification):
    firebase_app()
    fcm_token_list = get_user_fcm_tokens(notification.for_user)
    message = notification.email_content
    message = convert_message(message)
    subject = convert_message(notification.subject)
    logger.info(f"Going to send Push to user = {notification.for_user}")

    data = {
        "document_name": notification.document_name or '',
        "document_type": notification.document_type or '',
        "for_user": notification.for_user,
        "from_user": notification.owner
    }
    if fcm_token_list:
        send_push_notification(fcm_token_list, subject, message, data)

def send_push_notification(tokens, title, body, data=None):
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body
        ),
        data=data,
        tokens=tokens
    )

    # Send the message
    response = messaging.send_each_for_multicast(message)
    logger.info(f"Push Notification sent Successfully, res = {response}")
