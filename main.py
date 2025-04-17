from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
import json
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import gspread
from google.oauth2.service_account import Credentials
import requests

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ENVIRONMENT
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Setup
creds = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_CREDENTIALS")),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
worksheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

GOOGLE_MAPS_API_KEY = "AIzaSyCMeu5AA1lG1Ty3NPrUz9W6G91-T0ruYN8"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

pricing_config = {
    "Home to Home": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "In-House Move": {"base": 40, "per_mile": 0, "per_ft3": 0.5, "per_item": 2.5},
    "Store Pickup": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "Junk Removal": {"base": 100, "per_mile": 0, "per_ft3": 0.1, "per_item": 5}
}

@app.post("/submit")
async def submit_move(
    data: str = Form(...),
    files: Optional[List[UploadFile]] = File(None)
):
    try:
        data_obj = json.loads(data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    # Extract fields
    name = data_obj.get("name", "")
    email = data_obj.get("email", "")
    phone = data_obj.get("phone", "")
    move_type = data_obj.get("move_type", "")
    pickup_address = data_obj.get("pickup_address", "")
    destination_address = data_obj.get("destination_address", "")
    current_lat = data_obj.get("current_lat")
    current_lng = data_obj.get("current_lng")
    mileage_override = data_obj.get("mileage_override")
    use_photos = data_obj.get("use_photos", False)
    items = data_obj.get("items", [])

    # Calculate distance
    distance_miles = 0
    if not mileage_override and pickup_address and destination_address:
        r = requests.get(DISTANCE_MATRIX_URL, params={
            "origins": pickup_address,
            "destinations": destination_address,
            "key": GOOGLE_MAPS_API_KEY,
            "units": "imperial"
        }).json()

        try:
            rows = r.get("rows", [])
            if rows and rows[0]["elements"] and rows[0]["elements"][0]["status"] == "OK":
                distance_text = rows[0]["elements"][0]["distance"]["text"]
                distance_miles = float(distance_text.replace("mi", "").strip()) if "mi" in distance_text else 0.01
        except Exception:
            distance_miles = 0.01

    if mileage_override is not None:
        distance_miles = mileage_override

    # Calculate price
    price = 0
    if not use_photos:
        total_ft3 = sum(
            (item["length"] * item["width"] * item["height"]) / 1728 for item in items
        )
        config = pricing_config.get(move_type, pricing_config["Home to Home"])
        price = config["base"] + config["per_mile"] * distance_miles + config["per_ft3"] * total_ft3 + config["per_item"] * len(items)

    # Log to Google Sheets
    timestamp = datetime.datetime.now().isoformat()
    worksheet.append_row([
        timestamp,
        name,
        email,
        phone,
        move_type,
        pickup_address,
        destination_address,
        distance_miles,
        len(items),
        ", ".join(item["item_name"] for item in items) if not use_photos else "",
        round(price, 2),
        "Auto" if use_photos else "Manual",
        "Yes" if use_photos else "No"
    ])

    # Send Email
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = f"New PikUp Move Request from {name}"

    body = f"""New move request:

Name: {name}
Email: {email}
Phone: {phone}
Move Type: {move_type}
Pickup Address: {pickup_address}
Dropoff Address: {destination_address}
Distance: {distance_miles} miles
Items: {', '.join(item['item_name'] for item in items) if items else 'Uploaded Photos'}
Estimated Price: ${round(price, 2) if price else 'Pending'}
"""
    msg.attach(MIMEText(body, "plain"))

    if files:
        for file in files:
            content = await file.read()
            part = MIMEBase("application", "octet-stream")
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={file.filename}")
            msg.attach(part)

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

    return {
        "status": "success",
        "estimated_price": round(price, 2) if price else "pending",
        "distance_miles": distance_miles
    }
