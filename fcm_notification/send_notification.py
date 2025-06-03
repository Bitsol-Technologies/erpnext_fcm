import frappe
import json
import re
import html
from frappe import enqueue
import firebase_admin
from firebase_admin import credentials, messaging

logger = frappe.logger("push_notification", allow_site=True, file_count=5)
logger.setLevel("WARNING")


def get_user_fcm_tokens(user_email):
	user_fcm_tokens = frappe.get_all(
		"User Device", filters={"user": user_email, "is_active": 1}, fields=["fcm_token"]
	)
	user_fcm_tokens = [f.get('fcm_token') for f in user_fcm_tokens if f]
	logger.warning(f"FCM tokens = {user_fcm_tokens}")
	return user_fcm_tokens


def send_push_to_user(email, title, message, data=None):
	firebase_app()
	fcm_token_list = get_user_fcm_tokens(email)
	if not fcm_token_list:
		return "No devices found or active"
	send_push_notification(fcm_token_list, title, message, data)


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
	# Replace <p> and </p> with newline characters
	html_text = re.sub(r'</?p>', '\n', message)
	# Remove all other HTML tags
	html_text = re.sub(r'<.*?>', '', html_text)
	# Convert &nbsp; and other HTML entities to plain text
	plain_text = html.unescape(html_text)
	# Strip extra leading/trailing newlines and spaces
	plain_text = plain_text.strip()
	# Remove consecutive newlines and replace with a single newline
	return re.sub(r'\n+', '\n', plain_text)


def firebase_app():
	try:
		# If it exists, this call will succeed and we do nothing.
		firebase_admin.get_app()
	except ValueError:
		try:
			server_key = frappe.db.get_single_value("FCM Notification Settings", "server_key")
			if not server_key:
				frappe.log_error(message="FCM Server key not found in 'FCM Notification Settings'. Firebase not initialized.", title="FCM Server Key Not Found")
				return 

			# server_key is expected to be a JSON string of the certificate
			cred_json = json.loads(server_key) 
			cred = credentials.Certificate(cred_json)
			firebase_admin.initialize_app(cred) # Initialize the default app
		except Exception as e_init:
			frappe.log_error(message=f"Error during Firebase app initialization attempt in fcm_notification: {e_init}", title="FCM Server Key Not Found")


def process_notification(notification):
	firebase_app()
	logger.warning(f'Notification {notification.push_text}, {notification.email_content}')
	message = str(notification.push_text or notification.email_content or '')
	message = convert_message(message)
	subject = convert_message(notification.subject)
	logger.warning(f"Going to send Push to user = {notification.for_user}, {notification}")

	data = {
		"document_name": str(notification.document_name or ''),
		"document_type": notification.document_type or '',
		"for_user": notification.for_user,
		"from_user": notification.owner,
		"name": str(notification.name or None)
	}
	fcm_token_list = get_user_fcm_tokens(notification.for_user)
	if fcm_token_list:
		send_push_notification(fcm_token_list, subject, message, data)


def send_push_notification(tokens, title, body, data=None):
	env = frappe.db.get_single_value("FCM Notification Settings", "environment")
	title = f"[{env}] {title}" if env else title
	message = messaging.MulticastMessage(
		notification=messaging.Notification(
			title=title,
			body=body
		),
		data=data,
		tokens=tokens
	)

	# Send the message
	res = messaging.send_each_for_multicast(message)
	logger.warning(f"Push sent Successfully, success_count = {res.success_count}, failure_count = {res.failure_count}")
	logger.info(f"Responses = {res.responses}")

