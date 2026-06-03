import os
import csv
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import requests
from groq import Groq, GroqError

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION & INITIALIZATION
# ─────────────────────────────────────────────────────────────────

load_dotenv(override=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()


def has_valid_groq_key() -> bool:
    """Returns True only when a real Groq key is configured."""
    return bool(GROQ_API_KEY) and "paste_your_groq_key_here" not in GROQ_API_KEY.lower()


client = Groq(api_key=GROQ_API_KEY) if has_valid_groq_key() else None

DATA_DIR = "data/raw"
DB_DIR = "data"

CROP_MAP = {
    "gari": "c_gari_fao",
    "cassava": "c_gari_fao",
    "maize": "c_maize_fao",
    "corn": "c_maize_fao",
    "rice": "c_rice_fao",
    "beans": "c_beans",
    "yam": "c_yam",
    "millet": "c_millet_fao",
    "sorghum": "c_sorghum_fao",
    "maize_flour": "c_maize_flour",
    "onions": "c_onions",
    "fish": "c_fish",
}

WFP_SEASONAL_PATTERNS = {
    "maize": {"peak_months": [7, 8, 9], "lowest_months": [1, 2, 3], "context": "Peak after June harvest; lows before new harvest"},
    "rice": {"peak_months": [6, 7, 8], "lowest_months": [11, 12, 1], "context": "Peaks in mid-year; lowest post-harvest"},
    "yam": {"peak_months": [8, 9, 10], "lowest_months": [4, 5, 6], "context": "Peak during harvest season; lows before"},
    "beans": {"peak_months": [7, 8], "lowest_months": [12, 1], "context": "Post-harvest peaks; dry season lows"},
    "default": {"peak_months": [6, 7, 8], "lowest_months": [1, 2], "context": "Typical seasonal variation"}
}

# ─────────────────────────────────────────────────────────────────
# DATA LAYER: Market Price Queries
# ─────────────────────────────────────────────────────────────────

def load_market_prices(region: str, crop: str, country: str = "Nigeria") -> dict:
    """
    Reads NGA_RTFP.csv or ETH_RTFP.csv and filters for region + crop.
    Returns current price, 1-month trend, and regional context.
    
    Args:
        region: State/Region name (e.g., "Ondo", "Lagos")
        crop: Crop type (e.g., "maize", "rice")
        country: "Nigeria" or "Ethiopia"
    
    Returns:
        dict with market data or None if failed
    """
    try:
        # Determine file path
        file_prefix = "NGA_RTFP" if country == "Nigeria" else "ETH_RTFP"
        file_path = os.path.join(DATA_DIR, f"{file_prefix}.csv")
        
        if not os.path.exists(file_path):
            print(f"⚠️  CSV file not found: {file_path}")
            return None
        
        # Normalize crop name
        crop_lower = crop.lower()
        column_name = CROP_MAP.get(crop_lower)
        
        if not column_name:
            print(f"⚠️  Crop '{crop}' not in mapping")
            return None
        
        # Read CSV efficiently
        df = pd.read_csv(file_path)
        
        # Filter by region and country
        region_data = df[
            (df['adm1_name'].str.lower() == region.lower()) |
            (df['mkt_name'].str.lower().str.contains(region.lower(), na=False))
        ].copy()
        
        if region_data.empty:
            print(f"⚠️  No data found for region: {region}")
            return None
        
        # Convert price_date to datetime
        region_data['price_date'] = pd.to_datetime(region_data['price_date'], errors='coerce')
        region_data = region_data.dropna(subset=['price_date'])
        
        # Sort by date (most recent first)
        region_data = region_data.sort_values('price_date', ascending=False)
        
        # Get current price (most recent entry)
        current_row = region_data.iloc[0]
        current_price = current_row[column_name]
        
        # Calculate 1-month trend
        one_month_ago = current_row['price_date'] - timedelta(days=30)
        historical = region_data[region_data['price_date'] <= one_month_ago]
        
        trend_direction = "Stable"
        trend_pct = 0.0
        
        if not historical.empty:
            old_price = historical.iloc[0][column_name]
            if pd.notna(old_price) and old_price > 0:
                trend_pct = ((current_price - old_price) / old_price) * 100
                if trend_pct > 5:
                    trend_direction = "Increasing"
                elif trend_pct < -5:
                    trend_direction = "Decreasing"
        
        return {
            "market_name": current_row['mkt_name'],
            "region": current_row.get('adm1_name', region),
            "country": country,
            "current_price": float(current_price) if pd.notna(current_price) else None,
            "currency": current_row.get('currency', 'NGN' if country == 'Nigeria' else 'ETB'),
            "trend_1m": trend_direction,
            "trend_pct": round(trend_pct, 2),
            "price_date": current_row['price_date'].strftime('%Y-%m-%d'),
            "regional_capital_price": None  # Would require second lookup to regional capital
        }
    
    except Exception as e:
        print(f"❌ Error loading market prices: {e}")
        return None


def get_historical_context(crop: str) -> dict:
    """
    Returns WFP seasonal patterns for the crop.
    """
    crop_lower = crop.lower()
    return WFP_SEASONAL_PATTERNS.get(crop_lower, WFP_SEASONAL_PATTERNS["default"])


# ─────────────────────────────────────────────────────────────────
# WEATHER LAYER: 5-Day Forecast
# ─────────────────────────────────────────────────────────────────

def fetch_5day_forecast(location: str) -> dict:
    """
    Fetches 5-day weather forecast from OpenWeather API.
    Calculates cumulative rainfall and humidity for Days 1-2 and Days 3-5.
    
    Returns:
        dict with forecast data or None if API fails
    """
    try:
        if not OPENWEATHER_API_KEY:
            print("⚠️  OPENWEATHER_API_KEY not set")
            return None
        
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={location}&appid={OPENWEATHER_API_KEY}&units=metric"
        response = requests.get(url, timeout=5)
        
        if response.status_code != 200:
            print(f"⚠️  Weather API error {response.status_code}")
            return None
        
        data = response.json()
        forecast_list = data.get('list', [])
        
        if not forecast_list:
            print("⚠️  No forecast data received")
            return None
        
        # Aggregate by day periods
        day1_2_rain = 0
        day1_2_humidity = []
        day3_5_rain = 0
        day3_5_humidity = []
        
        now = datetime.now()
        
        for entry in forecast_list:
            forecast_time = datetime.fromtimestamp(entry['dt'])
            days_ahead = (forecast_time - now).days
            
            rain = entry.get('rain', {}).get('3h', 0)
            humidity = entry.get('main', {}).get('humidity', 0)
            
            if days_ahead <= 2:
                day1_2_rain += rain
                day1_2_humidity.append(humidity)
            elif days_ahead <= 5:
                day3_5_rain += rain
                day3_5_humidity.append(humidity)
        
        avg_humidity_1_2 = sum(day1_2_humidity) / len(day1_2_humidity) if day1_2_humidity else 0
        avg_humidity_3_5 = sum(day3_5_humidity) / len(day3_5_humidity) if day3_5_humidity else 0
        
        heavy_rain_alert = day3_5_rain > 25 or day1_2_rain > 25  # > 25mm in single period
        high_humidity_alert = avg_humidity_1_2 > 70 or avg_humidity_3_5 > 70
        
        return {
            "location": data['city']['name'],
            "day1_2": {
                "rainfall_mm": round(day1_2_rain, 1),
                "humidity": round(avg_humidity_1_2, 1),
                "condition": "Humid" if avg_humidity_1_2 > 70 else "Moderate"
            },
            "day3_5": {
                "rainfall_mm": round(day3_5_rain, 1),
                "humidity": round(avg_humidity_3_5, 1),
                "condition": "Humid" if avg_humidity_3_5 > 70 else "Moderate"
            },
            "heavy_rain_alert": heavy_rain_alert,
            "high_humidity_alert": high_humidity_alert,
            "spoilage_risk": (day1_2_rain + day3_5_rain > 30) and high_humidity_alert
        }
    
    except requests.exceptions.Timeout:
        print("⚠️  Weather API timeout")
        return None
    except Exception as e:
        print(f"❌ Error fetching weather: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# GUARDRAIL LAYER: Constraint Enforcement
# ─────────────────────────────────────────────────────────────────

def check_guardrails(farmer_profile: dict, market_data: dict, weather: dict) -> dict:
    """
    Enforces 4 strict agricultural rules:
    1. Cash constraint: HIGH cash need → max 7 days hold
    2. Spoilage threat: rain>30mm + humidity>70% + open storage → immediate sell
    3. Logistics bottleneck: heavy rain Days 3-5 → sell before roads wash
    4. No fabrication: validates data exists
    
    Returns:
        dict with violations list and forced_action if critical
    """
    violations = []
    forced_action = None
    
    # Rule 1: Cash Constraint
    if farmer_profile.get('cash_need_level') == 'HIGH':
        violations.append("CASH_CONSTRAINT: HIGH cash need detected → max 7-day hold")
        forced_action = "SELL_IMMEDIATELY_WITHIN_7_DAYS"
    
    # Rule 2: Spoilage Threat
    if weather and weather.get('spoilage_risk') and farmer_profile.get('storage_capability') == 'Traditional open bags':
        total_rain = weather['day1_2']['rainfall_mm'] + weather['day3_5']['rainfall_mm']
        avg_humidity = (weather['day1_2']['humidity'] + weather['day3_5']['humidity']) / 2
        
        if total_rain > 30 and avg_humidity > 70:
            violations.append(f"SPOILAGE_THREAT: {total_rain}mm rain + {avg_humidity}% humidity + open storage → spoilage imminent")
            forced_action = "SELL_IMMEDIATELY"
    
    # Rule 3: Logistics Bottleneck
    if weather and weather['day3_5']['rainfall_mm'] > 25:
        violations.append(f"LOGISTICS_BOTTLENECK: Heavy rain ({weather['day3_5']['rainfall_mm']}mm) Days 3-5 → roads may wash out")
        if not forced_action:
            forced_action = "SELL_BY_DAY_2"
    
    # Rule 4: Data Validation
    if not market_data or not market_data.get('current_price'):
        violations.append("DATA_VALIDATION: No current price data available")
    
    return {
        "violations": violations,
        "forced_action": forced_action,
        "severity": "CRITICAL" if forced_action else "NONE"
    }


# ─────────────────────────────────────────────────────────────────
# LLM LAYER: Recommendation Generation
# ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Role: You are the elite Agricultural Economics AI Engine for HarvestBridge, specialized in smallholder supply chains in Nigeria and Ethiopia. Your job is to translate complex backend data arrays into an urgent, easy-to-read WhatsApp notification for a farmer.

Input Data Structure (Injected by main.py):
- FARMER: {location}, {crop}, {harvest_volume}, Storage: {storage_capability}, Cash Urgency: {cash_need_level}
- MARKET: Local Market: {market_name}, Current Price: {current_price} {currency}, 1-Month Trend: {trend_1m} ({trend_pct}%)
- WEATHER: Days 1-2 Rainfall: {day1_2_rain}mm, Humidity: {day1_2_humidity}%. Days 3-5 Rainfall: {day3_5_rain}mm, Humidity: {day3_5_humidity}%
- BACKEND GUARDRAIL STATUS: Forced Action Override: {forced_action}, Violations Detected: {violations}

Strict Instructional Logic:
1. ADHERE TO THE OVERRIDE: If 'Forced Action Override' is NOT None (e.g., 'SELL_IMMEDIATELY' or 'SELL_BY_DAY_2'), your recommendation MUST explicitly order that action. Do not contradict the backend Python logic.
2. NO NUMBER FABRICATION: Use only the exact prices, trends, and weather metrics provided in the data payload. Never invent external financial data.
3. TONAL RULES: Write like a trusted local farming co-op advisor. Use simple, direct language. Avoid corporate or academic jargon.

Output Structure (STRICT MAX 150 WORDS):
🚨 *HarvestBridge Alert: [Insert Crop Name] Action Plan*

• *Market Trend:* [1 short sentence explaining local prices and the 1-month trend]
• *Weather Risk:* [1 short sentence translating the rainfall/humidity numbers into direct crop rot or transport risks]

👉 *Recommended Action:* [Bold, clear instruction on exactly WHAT percentage to sell or hold, and WHEN to do it, matching the backend guardrail requirements].

---
Button 1: Connect to Local Buyers
Button 2: View Alternative Market Prices"""


def generate_recommendation(
    farmer_profile: dict,
    market_data: dict,
    weather: dict,
    guardrail_result: dict
) -> str:
    """
    Constructs LLM payload and calls Groq API with system prompt.
    Returns WhatsApp-ready notification string.
    """
    try:
        if not has_valid_groq_key() or client is None:
            return (
                "⚠️ AI recommendation is unavailable because GROQ_API_KEY is not configured. "
                "Using the backend guardrails only: sell immediately if cash or spoilage risk is critical."
            )
        
        # Build data payload for LLM using the exact HarvestBridge fields
        forced_action = guardrail_result.get('forced_action')
        violations = guardrail_result.get('violations', [])
        user_message = f"""
FARMER: {farmer_profile.get('location', 'Unknown')}, {farmer_profile.get('crop', 'Unknown')}, {farmer_profile.get('harvest_volume', 'Unknown')}, Storage: {farmer_profile.get('storage_capability', 'Unknown')}, Cash Urgency: {farmer_profile.get('cash_need_level', 'MEDIUM')}
MARKET: Local Market: {market_data.get('market_name', 'N/A')}, Current Price: {market_data.get('current_price', 'N/A')} {market_data.get('currency', 'NGN')}, 1-Month Trend: {market_data.get('trend_1m', 'Stable')} ({market_data.get('trend_pct', 0)}%)
WEATHER: Days 1-2 Rainfall: {weather.get('day1_2', {}).get('rainfall_mm', 0)}mm, Humidity: {weather.get('day1_2', {}).get('humidity', 0)}%. Days 3-5 Rainfall: {weather.get('day3_5', {}).get('rainfall_mm', 0)}mm, Humidity: {weather.get('day3_5', {}).get('humidity', 0)}%
BACKEND GUARDRAIL STATUS: Forced Action Override: {forced_action}, Violations Detected: {json.dumps(violations, ensure_ascii=False)}

Generate the final WhatsApp notification using only the exact data above and obey the strict output rules in the system prompt.
"""
        
        # Call Groq API
        completion = client.chat.completions.create(
            model="Llama-3.3-70B-Versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3,  # Low temperature for consistency
            max_tokens=300
        )
        
        recommendation = completion.choices[0].message.content.strip()
        return recommendation
    
    except GroqError as e:
        print(f"❌ Groq API error: {e}")
        return "⚠️ AI recommendation service is unavailable right now. Please review the guardrail advice and retry later."
    except Exception as e:
        print(f"❌ Error generating recommendation: {e}")
        return "⚠️ AI recommendation service is unavailable right now. Please review the guardrail advice and retry later."


# ─────────────────────────────────────────────────────────────────
# ORCHESTRATION: Main Entry Point
# ─────────────────────────────────────────────────────────────────

def process_farmer_inquiry(
    farmer_id: str,
    location: str,
    crop: str,
    harvest_volume: str,
    storage_capability: str,
    cash_need_level: str,
    country: str = "Nigeria"
) -> str:
    """
    Main orchestration function that chains all layers.
    
    Args:
        farmer_id: Unique identifier
        location: Region/State (e.g., "Ondo", "Lagos")
        crop: Crop type (e.g., "maize")
        harvest_volume: Volume (e.g., "20 bags")
        storage_capability: Storage type (e.g., "Traditional open bags")
        cash_need_level: "HIGH", "MEDIUM", "LOW"
        country: "Nigeria" or "Ethiopia"
    
    Returns:
        WhatsApp-ready notification string
    """
    print(f"\n{'='*60}")
    print(f"Processing inquiry for Farmer ID: {farmer_id}")
    print(f"Crop: {crop} | Location: {location} | Storage: {storage_capability}")
    print(f"{'='*60}\n")
    
    # Build farmer profile
    farmer_profile = {
        "farmer_id": farmer_id,
        "location": location,
        "country": country,
        "crop": crop,
        "harvest_volume": harvest_volume,
        "storage_capability": storage_capability,
        "cash_need_level": cash_need_level
    }
    
    # Step 1: Load market prices
    print("📊 Step 1: Loading market prices...")
    market_data = load_market_prices(location, crop, country)
    if not market_data:
        return "❌ Unable to fetch market data. Please try a different region or crop."
    print(f"✓ Market: {market_data['market_name']} | Price: {market_data['current_price']} {market_data['currency']}")
    
    # Step 2: Fetch weather forecast
    print("🌤️  Step 2: Fetching weather forecast...")
    weather = fetch_5day_forecast(location)
    if not weather:
        print("⚠️  Weather API unavailable, proceeding without weather data")
        weather = {
            "day1_2": {"rainfall_mm": 0, "humidity": 50, "condition": "Unknown"},
            "day3_5": {"rainfall_mm": 0, "humidity": 50, "condition": "Unknown"},
            "heavy_rain_alert": False,
            "spoilage_risk": False
        }
    else:
        print(f"✓ Weather: Days 1-2: {weather['day1_2']['rainfall_mm']}mm rain | Days 3-5: {weather['day3_5']['rainfall_mm']}mm rain")
    
    # Step 3: Check guardrails
    print("⚠️  Step 3: Checking guardrails...")
    guardrail_result = check_guardrails(farmer_profile, market_data, weather)
    if guardrail_result['violations']:
        for v in guardrail_result['violations']:
            print(f"   🚨 {v}")
    else:
        print("   ✓ No critical violations")
    
    # Step 4: Generate recommendation
    print("🤖 Step 4: Generating LLM recommendation...")
    recommendation = generate_recommendation(farmer_profile, market_data, weather, guardrail_result)
    
    print("\n📱 NOTIFICATION OUTPUT:")
    print(f"\n{recommendation}\n")
    
    return recommendation


# ─────────────────────────────────────────────────────────────────
# DEMO & TESTING
# ─────────────────────────────────────────────────────────────────

def main():
    """
    Demo: Process a sample farmer inquiry
    """
    result = process_farmer_inquiry(
        farmer_id="FARMER_001",
        location="Abia",
        crop="maize",
        harvest_volume="20 bags",
        storage_capability="Traditional open bags",
        cash_need_level="HIGH",
        country="Nigeria"
    )
    print("\n" + "="*60)
    print("FINAL WHATSAPP MESSAGE:")
    print("="*60)
    print(result)


if __name__ == "__main__":
    main()
