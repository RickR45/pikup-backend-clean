from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
from PIL import Image

# Initialize FastAPI app
app = FastAPI()

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load credentials
GOOGLE_SHEET_ID = "your_google_sheet_id_here"  # Replace!
EMAIL_ADDRESS = "your_email@gmail.com"          # Replace!
EMAIL_PASSWORD = "your_gmail_app_password_here" # Replace!

# Setup Google Sheets
creds = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_CREDENTIALS")),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
worksheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

# Google Distance Matrix
GOOGLE_MAPS_API_KEY = "AIzaSyCMeu5AA1lG1Ty3NPrUz9W6G91-T0ruYN8"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# Pricing
pricing_config = {
    "Home to Home": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "In-House Move": {"base": 40, "per_mile": 0, "per_ft3": 0.5, "per_item": 2.5},
    "Store Pickup": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "Junk Removal": {"base": 100, "per_mile": 0, "per_ft3": 0.1, "per_item": 5}
}

class ItemData(BaseModel):
    item_name: Optional[str]
    length: float
    width: float
    height: float
    use_ai: bool

# Accept multipart form: data + files
@app.post("/submit")
async def submit_move(
    data: str = Form(...),
    files: List[UploadFile] = File(None)
):
    data_obj = json.loads(data)

    name = data_obj.get("name")
    email = data_obj.get("email")
    phone = data_obj.get("phone")
    move_type = data_obj.get("move_type")
    pickup_address = data_obj.get("pickup_address")
    destination_address = data_obj.get("destination_address")
    current_lat = data_obj.get("current_lat")
    current_lng = data_obj.get("current_lng")
    mileage_override = data_obj.get("mileage_override")
    use_photos = data_obj.get("use_photos", False)
    items = data_obj.get("items", [])

    # Calculate distance
    distance_miles = 0
    if not mileage_override and pickup_address and destination_address:
        response = requests.get(DISTANCE_MATRIX_URL, params={
            "origins": pickup_address,
            "destinations": destination_address,
            "key": GOOGLE_MAPS_API_KEY,
            "units": "imperial"
        }).json()

        try:
            rows = response.get("rows", [])
            if rows and rows[0]["elements"] and rows[0]["elements"][0]["status"] == "OK":
                distance_text = rows[0]["elements"][0]["distance"]["text"]
                if "mi" in distance_text:
                    distance_miles = float(distance_text.replace("mi", "").strip())
                elif "ft" in distance_text:
                    distance_miles = 0.01
                else:
                    distance_miles = 0.01
        except Exception as e:
            print("Distance calc failed:", e)

    if mileage_override is not None:
        distance_miles = mileage_override

    # Estimate price
    price = 0
    if not use_photos:
        total_ft3 = sum(
            (item["length"] * item["width"] * item["height"]) / 1728 for item in items
        )
        item_count = len(items)
        config = pricing_config.get(move_type, pricing_config["Home to Home"])
        price = config["base"] + config["per_mile"] * distance_miles + config["per_ft3"] * total_ft3 + config["per_item"] * item_count

    # Save to Google Sheets
    timestamp = datetime.datetime.now().isoformat()
    image_status = "Yes" if use_photos else "No"
    item_list = ", ".join(item["item_name"] for item in items) if not use_photos else ""

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
        item_list,
        round(price, 2),
        "Auto" if use_photos else "Manual",
        image_status
    ])

    # Send Email
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = f"New PikUp Submission - {name}"

    body = f"""New Move Request:

Name: {name}
Email: {email}
Phone: {phone}
Move Type: {move_type}
Pickup Address: {pickup_address}
Dropoff Address: {destination_address}
Distance: {distance_miles} miles
Items: {item_list if item_list else 'Photos uploaded'}
Estimated Price: ${round(price, 2) if price else 'Pending'}
"""
    msg.attach(MIMEText(body, "plain"))

    if files:
        for file in files:
            file_content = await file.read()
            part = MIMEBase("application", "octet-stream")
            part.set_payload(file_content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={file.filename}")
            msg.attach(part)

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    server.send_message(msg)
    server.quit()

    if use_photos:
        return {"status": "success", "message": "Photos received. We will quote you soon."}
    else:
        return {"status": "success", "estimated_price": round(price, 2), "distance_miles": distance_miles}
