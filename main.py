from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import List, Optional, Dict
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
import secrets
from pydantic import BaseModel

app = FastAPI()
import pprint

# Admin Authentication
security = HTTPBasic()

def get_admin_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("ADMIN_USERNAME")
    correct_password = os.getenv("ADMIN_PASSWORD")
    
    is_correct_username = secrets.compare_digest(credentials.username.encode("utf8"), correct_username.encode("utf8"))
    is_correct_password = secrets.compare_digest(credentials.password.encode("utf8"), correct_password.encode("utf8"))
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials

# Driver Authentication Models
class DriverLogin(BaseModel):
    email: str
    password: str

class DriverResponse(BaseModel):
    name: str
    email: str
    phone: str
    vehicle_type: str
    license_number: str
    address: str
    status: str
    total_earnings: float
    completed_moves: int
    rating: float

# Driver Authentication
def get_driver_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    try:
        drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
        drivers = drivers_sheet.get_all_records()
        
        # Find driver by email
        driver = next((d for d in drivers if d["email"] == credentials.username), None)
        
        if not driver:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Driver not found",
                headers={"WWW-Authenticate": "Basic"},
            )
            
        # Check password from sheet
        if credentials.password != driver.get("password", ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password",
                headers={"WWW-Authenticate": "Basic"},
            )
            
        return driver
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Driver Endpoints
@app.post("/driver/login")
async def driver_login(login_data: DriverLogin):
    try:
        drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
        drivers = drivers_sheet.get_all_records()
        
        # Find driver by email
        driver = next((d for d in drivers if d["email"] == login_data.email), None)
        
        if not driver:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Driver not found"
            )
            
        # Check password from sheet
        if login_data.password != driver.get("password", ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password"
            )
            
        return {
            "status": "success",
            "message": "Login successful",
            "driver": {
                "name": driver["name"],
                "email": driver["email"],
                "status": driver["status"]
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/driver/profile")
async def get_driver_profile(credentials: HTTPBasicCredentials = Depends(get_driver_credentials)):
    try:
        return {
            "status": "success",
            "driver": {
                "name": credentials["name"],
                "email": credentials["email"],
                "phone": credentials["phone"],
                "vehicle_type": credentials["vehicle_type"],
                "license_number": credentials["license_number"],
                "address": credentials["address"],
                "status": credentials["status"],
                "total_earnings": float(credentials["total_earnings"]),
                "completed_moves": int(credentials["completed_moves"]),
                "rating": float(credentials["rating"])
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@app.get("/driver/moves")
async def get_driver_moves(credentials: HTTPBasicCredentials = Depends(get_driver_credentials)):
    try:
        # Get moves from the main worksheet
        moves_sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        moves = moves_sheet.get_all_records()
        
        # Filter moves for this driver (in a real app, you'd have a driver_id field)
        driver_moves = [
            move for move in moves 
            if move.get("driver_email") == credentials["email"]
        ]
        
        return {
            "status": "success",
            "moves": driver_moves
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Driver Management Endpoints
@app.post("/admin/drivers")
async def add_driver(
    driver_data: Dict,
    credentials: HTTPBasicCredentials = Depends(get_admin_credentials)
):
    try:
        # Validate required fields
        required_fields = ["name", "email", "phone", "vehicle_type", "license_number"]
        for field in required_fields:
            if field not in driver_data:
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
        
        # Get the drivers worksheet
        drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
        
        # Check if driver email already exists
        existing_drivers = drivers_sheet.get_all_records()
        if any(driver["email"] == driver_data["email"] for driver in existing_drivers):
            raise HTTPException(status_code=400, detail="Driver with this email already exists")
        
        # Prepare driver data
        driver_row = [
            datetime.datetime.now().isoformat(),  # Timestamp
            driver_data["name"],
            driver_data["email"],
            driver_data["phone"],
            driver_data["vehicle_type"],
            driver_data["license_number"],
            driver_data.get("address", ""),
            driver_data.get("notes", ""),
            "Active",  # Status
            "0",  # Total Earnings
            "0",  # Completed Moves
            "0"   # Rating
        ]
        
        # Add to sheet
        drivers_sheet.append_row(driver_row)
        
        return {"status": "success", "message": "Driver added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/drivers")
async def get_drivers(credentials: HTTPBasicCredentials = Depends(get_admin_credentials)):
    try:
        drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
        drivers = drivers_sheet.get_all_records()
        return {"status": "success", "drivers": drivers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/admin/drivers/{email}")
async def update_driver(
    email: str,
    driver_data: Dict,
    credentials: HTTPBasicCredentials = Depends(get_admin_credentials)
):
    try:
        drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
        drivers = drivers_sheet.get_all_records()
        
        # Find driver row
        driver_row = None
        for i, driver in enumerate(drivers, start=2):  # start=2 because sheet is 1-indexed and has header
            if driver["email"] == email:
                driver_row = i
                break
        
        if not driver_row:
            raise HTTPException(status_code=404, detail="Driver not found")
        
        # Update fields
        update_data = []
        for field in ["name", "phone", "vehicle_type", "license_number", "address", "notes", "status"]:
            if field in driver_data:
                update_data.append(driver_data[field])
            else:
                # Get existing value
                col_index = drivers_sheet.row_values(1).index(field) + 1
                update_data.append(drivers_sheet.cell(driver_row, col_index).value)
        
        # Update row
        drivers_sheet.update(f"B{driver_row}:H{driver_row}", [update_data])
        
        return {"status": "success", "message": "Driver updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/admin/drivers/{email}")
async def delete_driver(
    email: str,
    credentials: HTTPBasicCredentials = Depends(get_admin_credentials)
):
    try:
        drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
        drivers = drivers_sheet.get_all_records()
        
        # Find driver row
        driver_row = None
        for i, driver in enumerate(drivers, start=2):
            if driver["email"] == email:
                driver_row = i
                break
        
        if not driver_row:
            raise HTTPException(status_code=404, detail="Driver not found")
        
        # Delete row
        drivers_sheet.delete_rows(driver_row)
        
        return {"status": "success", "message": "Driver deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

# Load credentials from file
creds = Credentials.from_service_account_file(
    "google-credentials.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)

gc = gspread.authorize(creds)
worksheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

# Create Drivers worksheet if it doesn't exist
try:
    drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Drivers")
except gspread.exceptions.WorksheetNotFound:
    # Create new worksheet
    drivers_sheet = gc.open_by_key(GOOGLE_SHEET_ID).add_worksheet(
        title="Drivers",
        rows=1000,
        cols=20
    )
    # Add headers
    headers = [
        "Timestamp",
        "Name",
        "Email",
        "Phone",
        "Vehicle Type",
        "License Number",
        "Address",
        "Notes",
        "Status",
        "Total Earnings",
        "Completed Moves",
        "Rating"
    ]
    drivers_sheet.append_row(headers)
    
    # Format headers
    drivers_sheet.format("A1:L1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
        "horizontalAlignment": "CENTER"
    })
    
    # Set column widths
    drivers_sheet.set_column_width(1, 180)  # Timestamp
    drivers_sheet.set_column_width(2, 150)  # Name
    drivers_sheet.set_column_width(3, 200)  # Email
    drivers_sheet.set_column_width(4, 120)  # Phone
    drivers_sheet.set_column_width(5, 150)  # Vehicle Type
    drivers_sheet.set_column_width(6, 150)  # License Number
    drivers_sheet.set_column_width(7, 250)  # Address
    drivers_sheet.set_column_width(8, 300)  # Notes
    drivers_sheet.set_column_width(9, 100)  # Status
    drivers_sheet.set_column_width(10, 120)  # Total Earnings
    drivers_sheet.set_column_width(11, 120)  # Completed Moves
    drivers_sheet.set_column_width(12, 100)  # Rating
    
    # Add data validation for Status column
    status_rule = {
        "condition": {
            "type": "ONE_OF_LIST",
            "values": ["Active", "Inactive", "On Leave", "Suspended"]
        },
        "showCustomUi": True,
        "strict": True
    }
    drivers_sheet.set_data_validation(9, 9, 1000, 9, status_rule)
    
    # Add data validation for Vehicle Type column
    vehicle_rule = {
        "condition": {
            "type": "ONE_OF_LIST",
            "values": ["Pickup Truck", "Van", "Box Truck", "Moving Truck"]
        },
        "showCustomUi": True,
        "strict": True
    }
    drivers_sheet.set_data_validation(5, 5, 1000, 5, vehicle_rule)
    
    # Add conditional formatting for Status
    status_format = {
        "ranges": [{"sheetId": drivers_sheet.id, "startRowIndex": 1, "endRowIndex": 1000, "startColumnIndex": 8, "endColumnIndex": 9}],
        "booleanRule": {
            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Inactive"}]},
            "format": {"backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}}
        }
    }
    drivers_sheet.spreadsheet.batch_update({"requests": [{"addConditionalFormatRule": {"rule": status_format}}]})
    
    # Add number formatting for earnings and moves
    drivers_sheet.format("J2:J1000", {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}})
    drivers_sheet.format("K2:K1000", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
    drivers_sheet.format("L2:L1000", {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}})
    
    # Freeze header row
    drivers_sheet.freeze(rows=1)

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# Pricing
pricing_config = {
    "Home to Home": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "In-House Move": {"base": 40, "per_mile": 0, "per_ft3": 0.5, "per_item": 2.5},
    "Store Pickup": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5},
    "Junk Removal": {"base": 100, "per_mile": 0, "per_ft3": 0.1, "per_item": 5},
    "Party/Venue": {"base": 100, "per_mile": 3, "per_ft3": 0.5, "per_item": 5}  # Same as Home to Home
}

STAIRS_SURCHARGE = 50  # Flat fee for stairs

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
    has_stairs = data_obj.get("has_stairs", False)
    items = data_obj.get("items", [])
    additional_info = data_obj.get("additional_info", "")
    scheduled_date = data_obj.get("scheduled_date", "")  # Format: YYYY-MM-DD
    scheduled_time = data_obj.get("scheduled_time", "")  # Format: HH:MM

    # Combine date and time as local time
    try:
        scheduled_datetime = datetime.datetime.strptime(f"{scheduled_date} {scheduled_time}", "%Y-%m-%d %H:%M")
        formatted_date = scheduled_datetime.strftime("%B %d, %Y at %I:%M %p")
    except Exception as e:
        print(f"Error parsing scheduled date/time: {str(e)}")
        formatted_date = f"{scheduled_date} {scheduled_time}"  # Fallback to raw strings if parsing fails

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
    stairs_charge = 0
    if not use_photos:
        total_ft3 = sum(
            (item["length"] * item["width"] * item["height"]) / 1728 for item in items
        )
        config = pricing_config.get(move_type, pricing_config["Home to Home"])
        price = config["base"] + config["per_mile"] * distance_miles + config["per_ft3"] * total_ft3 + config["per_item"] * len(items)
        if has_stairs:
            stairs_charge = STAIRS_SURCHARGE
            price += stairs_charge

    # Save to Google Sheets
    timestamp = datetime.datetime.now().isoformat()
    
    # Get the next empty row
    next_row = len(worksheet.get_all_values()) + 1
    
    # Update the row starting from column A
    worksheet.update(f'A{next_row}:R{next_row}', [[
        timestamp,  # Timestamp
        name,  # Name
        email,  # Email
        phone,  # Phone
        move_type,  # Item
        move_type,  # Move Type
        pickup_address,  # Pickup Address
        destination_address,  # Dropoff Address
        formatted_date,  # Scheduled date and time of move
        distance_miles,  # Distance
        len(items),  # Item Count
        ", ".join(item["item_name"] for item in items) if not use_photos else "",  # Items
        "Yes" if use_photos else "No",  # Image upload
        "Yes" if has_stairs else "No",  # Has Stairs
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
Scheduled Date/Time: {formatted_date}
Distance: {distance_miles} miles
Items: {', '.join(item['item_name'] for item in items) if items else 'Uploaded Photos'}
Has Stairs: {'Yes' if has_stairs else 'No'}
{'Stairs Surcharge: $' + str(stairs_charge) if has_stairs else ''}
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
Number of Items: {'Pending' if use_photos else len(items)}
Items: {', '.join(item['item_name'] for item in items) if items else 'Uploaded Photos'}
Has Stairs: {'Yes' if has_stairs else 'No'}
{'Stairs Surcharge: $' + str(stairs_charge) if has_stairs else ''}
Special Instructions: {additional_info if additional_info else 'None provided'}
Estimated Price: ${round(price, 2) if price else 'Pending'}

{('We will review your uploaded photos and send you a price quote within the next 24 hours.' if use_photos else '')}

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
