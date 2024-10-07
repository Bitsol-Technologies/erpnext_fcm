import frappe
import json
from frappe import enqueue
import re
import firebase_admin
from firebase_admin import credentials, messaging


def user_id(doc):
    user_email = doc.for_user
    user_device_id = frappe.get_all(
        "User Device", filters={"user": user_email, "is_active": 1}, fields=["device_id"]
    )
    return user_device_id


@frappe.whitelist()
def create_or_update_user_device(device_id, device_name, device_manufacturer, fcm_token):
    user = frappe.session.user
    user_device_id = frappe.get_all(
        "User Device", filters={"user": user}, fields=["device_id"]
    )
    if user_device_id:
        user_device = frappe.get_doc("User Device", {"user": user})
        user_device.device_name = device_name
        user_device.device_manufacturer = device_manufacturer
        user_device.device_id = device_id
        user_device.fcm_token = fcm_token
        user_device.is_active = 1
        user_device.save()
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


@frappe.whitelist()
def mark_device_as_inactive(email):
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
    firebase_admin.initialize_app(cred)

def process_notification(device_id, notification):
    firebase_app()
    fcm_token_list = get_user_fcm_token_list(notification.for_user)
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
    if fcm_token_list:
        send_push_notification(fcm_token_list, notification.subject, message, data)


def get_user_fcm_token_list(user):
    return frappe.db.get_list("User Device", {"user": user}, ["fcm_token"])

def get_doc_owner_name(email):
    return frappe.db.get_value("Employee", {"user_id": email}, ["employee_name"])

def send_push_notification(fcm_token_list, title, body, data=None):
    for fcm_token in fcm_token_list:
        notification = messaging.Notification(title=title, body=body)
        message = messaging.Message(notification=notification, token=fcm_token["fcm_token"], data=data)
        messaging.send(message)
