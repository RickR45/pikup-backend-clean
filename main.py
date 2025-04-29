from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
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
import pprint

@app.get("/test-distance")
async def test_distance():
    try:
        response = requests.get(DISTANCE_MATRIX_URL, params={
            "origins": "521 Red Drew Ave, Tuscaloosa, AL 35401",
            "destinations": "92 Springbrook Cir, Tuscaloosa, AL 35405",
            "key": GOOGLE_MAPS_API_KEY,
            "units": "imperial"
        })
        data = response.json()
        pprint.pprint(data)
        return data
    except Exception as e:
        return {"error": str(e)}


# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment Variables
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Google Credentials
from google.oauth2.service_account import Credentials
import os

# Correct way: Load from local file (make sure google-credentials.json exists in your folder)
creds = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_CREDENTIALS")),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

gc = gspread.authorize(creds)
worksheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# Pricing
pricing_config = {
    "Home to Home": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "In-House Move": {"base": 40, "per_mile": 0, "per_ft3": 0.5, "per_item": 2.5},
    "Store Pickup": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "Junk Removal": {"base": 100, "per_mile": 0, "per_ft3": 0.1, "per_item": 5}
}

@app.post("/submit")
async def submit_move(
    request: Request,
    data: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None)
):
    try:
        # Safe parsing
        if data is not None:
            try:
                data_obj = json.loads(data)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid FormData JSON provided.")
        else:
            try:
                data_obj = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body provided.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Problem reading input: {str(e)}")

    # Extracting fields
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
    additional_info = data_obj.get("additional_info", "")

    # Distance Calculation
    distance_miles = 0
    distance_miles = 0
    if not mileage_override and pickup_address and destination_address:
        try:
            response = requests.get(DISTANCE_MATRIX_URL, params={
                "origins": pickup_address,
                "destinations": destination_address,
                "key": GOOGLE_MAPS_API_KEY,
                "units": "imperial"
            })
            if response.status_code == 200:
                distance_data = response.json()
                rows = distance_data.get("rows")
                if rows:
                    elements = rows[0].get("elements")
                    if elements and elements[0].get("status") == "OK":
                        distance_meters = elements[0]["distance"]["value"]
                        distance_miles = distance_meters / 1609.34
                        distance_miles = round(distance_miles, 2)
                    else:
                        print("No valid elements returned from Distance Matrix API.")
                else:
                    print("No valid rows returned from Distance Matrix API.")
            else:
                print(f"Distance API error: {response.status_code}")
        except Exception as e:
            print(f"Distance calculation failed: {str(e)}")

    # Only override if a real mileage_override was provided
    if mileage_override not in (None, "", 0):
        distance_miles = mileage_override

    # Price Estimation
    price = 0
    if not use_photos:
        total_ft3 = sum(
            (item["length"] * item["width"] * item["height"]) / 1728 for item in items
        )
        config = pricing_config.get(move_type, pricing_config["Home to Home"])
        price = config["base"] + config["per_mile"] * distance_miles + config["per_ft3"] * total_ft3 + config["per_item"] * len(items)

    # Save to Google Sheets
    timestamp = datetime.datetime.now().isoformat()
    
    # Get the next empty row
    next_row = len(worksheet.get_all_values()) + 1
    
    # Update the row starting from column A
    worksheet.update(f'A{next_row}:Q{next_row}', [[
        timestamp,  # Timestamp
        name,  # Name
        email,  # Email
        phone,  # Phone
        move_type,  # Item
        move_type,  # Move Type
        pickup_address,  # Pickup Address
        destination_address,  # Dropoff Address
        timestamp,  # Date and time of move
        distance_miles,  # Distance
        len(items),  # Item Count
        ", ".join(item["item_name"] for item in items) if not use_photos else "",  # Items
        "Yes" if use_photos else "No",  # Image upload
        additional_info,  # Special Instructions
        round(price, 2),  # Price
        round(price * 0.7, 2),  # Driver pay (70% of total price)
        round(price * 0.3, 2)  # Business profit (30% of total price)
    ]])

    # Send Email to Admin
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
Special Instructions: {additional_info if additional_info else 'None provided'}
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

    # Send Confirmation Email to User
    user_msg = MIMEMultipart()
    user_msg["From"] = EMAIL_ADDRESS
    user_msg["To"] = email
    user_msg["Subject"] = "Your PikUp Move Request Confirmation"

    # Format the timestamp in American style
    move_date = datetime.datetime.fromisoformat(timestamp)
    formatted_date = move_date.strftime("%B %d, %Y at %I:%M %p")

    user_body = f"""Thank you for choosing PikUp! Here are the details of your move request:

Move Details:
------------
Name: {name}
Email: {email}
Phone: {phone}
Move Type: {move_type}
Pickup Address: {pickup_address}
Dropoff Address: {destination_address}
Scheduled Date/Time: {formatted_date}
Distance: {distance_miles} miles
Number of Items: {len(items)}
Items: {', '.join(item['item_name'] for item in items) if items else 'Uploaded Photos'}
Special Instructions: {additional_info if additional_info else 'None provided'}
Estimated Price: ${round(price, 2) if price else 'Pending'}

We're connecting you with a driver who will contact you before your scheduled move time.

If you have any questions or need to make changes to your request, please contact us at {EMAIL_ADDRESS}

Thank you for choosing PikUp!
"""
    user_msg.attach(MIMEText(user_body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    server.send_message(user_msg)
    server.quit()

    return {
        "status": "success",
        "estimated_price": round(price, 2) if price else "pending",
        "distance_miles": distance_miles
    }
