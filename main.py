import os
import json
import datetime
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from google.cloud import vision
from google.oauth2 import service_account
from dotenv import load_dotenv
import gspread

# Load environment variables
load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
GOOGLE_CREDENTIALS_PATH = "google-credentials.json"

# Write Google credentials to file before anything else
if GOOGLE_CREDS_JSON:
    try:
        with open(GOOGLE_CREDENTIALS_PATH, "w") as f:
            f.write(GOOGLE_CREDS_JSON)
        print("✅ google-credentials.json written successfully.")
    except Exception as e:
        print("❌ Failed to write google-credentials.json:", e)
else:
    print("⚠️ GOOGLE_CREDS_JSON is empty or missing.")

# Initialize FastAPI app
app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Google service credentials setup
creds = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDENTIALS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

# Google Sheets setup
gc = gspread.authorize(creds)
SHEET_ID = "1vQXczKHiu8mc8S6u9WdtsjwE17_Jp4565C9p-ZiGPJY"
worksheet = gc.open_by_key(SHEET_ID).sheet1

# Google Maps API
GOOGLE_MAPS_API_KEY = "AIzaSyCMeu5AA1lG1Ty3NPrUz9W6G91-T0ruYN8"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# Pricing config
pricing_config = {
    "Home to Home": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "In-House Move": {"base": 40, "per_mile": 0, "per_ft3": 0.5, "per_item": 2.5},
    "Store Pickup": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "Junk Removal": {"base": 100, "per_mile": 0, "per_ft3": 0.1, "per_item": 5}
}

# Models
class ItemData(BaseModel):
    item_name: Optional[str]
    length: float
    width: float
    height: float
    use_ai: bool
    vision_confidence: Optional[float] = None

class MoveData(BaseModel):
    name: str
    email: str
    phone: str
    move_type: str
    pickup_address: Optional[str] = ""
    destination_address: str
    current_lat: float
    current_lng: float
    mileage_override: Optional[float] = None
    use_photos: bool
    items: List[ItemData]

# Email helper
def send_notification_email(name, email, phone, use_photos, attachments):
    msg = MIMEMultipart()
    msg["Subject"] = "New PikUp Move Submission"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    body = f"New move submitted by {name}\nEmail: {email}\nPhone: {phone}\nUsed Images: {use_photos}"
    msg.attach(MIMEText(body, "plain"))

    for file_path in attachments:
        with open(file_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
            msg.attach(part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print("Email failed:", e)

@app.post("/submit")
async def submit_move(data: MoveData):
    origin = f"{data.current_lat},{data.current_lng}"
    destination = data.destination_address

    distance_miles = 0.0
    result = {}
    if data.mileage_override is not None:
        distance_miles = data.mileage_override
    else:
        response = requests.get(DISTANCE_MATRIX_URL, params={
            "origins": origin,
            "destinations": destination,
            "key": GOOGLE_MAPS_API_KEY,
            "units": "imperial"
        })
        result = response.json()
        try:
            rows = result.get("rows", [])
            if rows and rows[0]["elements"] and rows[0]["elements"][0]["status"] == "OK":
                distance_text = rows[0]["elements"][0]["distance"]["text"]
                if "mi" in distance_text:
                    distance_miles = float(distance_text.replace("mi", "").strip())
                elif "ft" in distance_text:
                    distance_miles = 0.01
            else:
                return {"error": "Could not calculate distance", "raw_response": result}
        except:
            return {"error": "Distance parse failed", "raw_response": result}

    total_ft3 = 0
    item_count = len(data.items)
    item_names = []

    for item in data.items:
        ft3 = (item.length * item.width * item.height) / 1728
        total_ft3 += ft3
        item_names.append(item.item_name or "Unknown")

    config = pricing_config.get(data.move_type, pricing_config["Home to Home"])
    price = config["base"] + config["per_mile"] * distance_miles + config["per_ft3"] * total_ft3 + config["per_item"] * item_count

    timestamp = datetime.datetime.now().isoformat()
    attachments = []

    if data.use_photos:
        worksheet.append_row([
            timestamp, data.name, data.email, data.phone, "", data.move_type,
            data.pickup_address or "", data.destination_address,
            round(distance_miles, 2), item_count, "", "YES", round(price, 2), "Auto", ""
        ])
    else:
        for item in data.items:
            worksheet.append_row([
                timestamp,
                data.name,
                data.email,
                data.phone,
                item.item_name or "Auto-detected",
                data.move_type,
                data.pickup_address or "",
                data.destination_address,
                round(distance_miles, 2),
                item_count,
                ", ".join(item_names),
                "NO",
                round(price, 2),
                "Auto" if item.use_ai else "Manual",
                item.vision_confidence or ""
            ])

    send_notification_email(data.name, data.email, data.phone, data.use_photos, attachments)

    return {
        "status": "success",
        "estimated_price": round(price, 2),
        "distance_miles": distance_miles
    }
