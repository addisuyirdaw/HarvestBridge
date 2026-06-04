import os
import re
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, Optional

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:
    FastAPI = None  # type: ignore
    HTTPException = Exception  # type: ignore
    BaseModel = object  # type: ignore

# In-memory database for Jimma coffee cherry washing stations.
STATION_DB: Dict[str, Dict[str, Any]] = {
    "agaro_primary_coop": {
        "station_name": "Agaro Primary Cooperative",
        "station_type": "Cooperative",
        "latitude": 7.851,
        "longitude": 36.652,
        "base_cherry_price": 215,
        "dividend_estimate": 20,
        "crops": ["coffee"],
    },
    "kata_muduga_mill": {
        "station_name": "Kata Muduga Private Mill",
        "station_type": "Private_Mill",
        "latitude": 7.865,
        "longitude": 36.671,
        "base_cherry_price": 235,
        "dividend_estimate": 0,
        "crops": ["coffee"],
    },
    "bale_agricultural_union_hub": {
        "station_name": "Bale Agricultural Union Hub",
        "station_type": "Union",
        # coordinates chosen to be plausibly near Jimma region for demo
        "latitude": 7.740,
        "longitude": 36.700,
        # prices stored in ETB/Quintal for wheat
        "base_cherry_price": 4100,
        "dividend_estimate": 0,
        "crops": ["wheat"],
    },
    "north_shewa_grain_center": {
        "station_name": "North Shewa Grain Collection Center",
        "station_type": "Collection_Center",
        # coordinates chosen to be plausibly north of Addis for demo
        "latitude": 9.000,
        "longitude": 39.000,
        # prices stored in ETB/Quintal for teff
        "base_cherry_price": 9200,
        "dividend_estimate": 0,
        "crops": ["teff"],
    },
}

TRANSPORT_COST_PER_KM = 5
HEAVY_RAIN_SPOILAGE_PENALTY = 40
HEAVY_RAIN_DISTANCE_KM = 2.5

HISTORICAL_MARKET_TRENDS = {
    "Ethiopia": {
        "coffee": {
            "months": ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"],
            "prices": [190, 210, 235, 233, 240, 245],
            "currency": "ETB",
            "market_name": "Jimma Coffee Cherry Market",
        }
        ,
        "wheat": {
            "months": ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"],
            "prices": [4100, 4300, 4600, 4800, 4750, 4900],
            "currency": "ETB/Quintal",
            "market_name": "Bale Wheat Market",
        },
        "teff": {
            "months": ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"],
            "prices": [9200, 9500, 10200, 10800, 11300, 11800],
            "currency": "ETB/Quintal",
            "market_name": "North Shewa Teff Market",
        }
    },
    "Nigeria": {
        "maize": {
            "months": ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"],
            "prices": [150000, 145000, 140000, 138000, 135000, 130000],
            "currency": "NGN",
            "market_name": "Ondo Maize Market",
        }
    },
}


def get_historical_market_trend(country: str, crop: str) -> Dict[str, Any]:
    country_data = HISTORICAL_MARKET_TRENDS.get(country, {})
    return country_data.get(crop.lower(), {
        "months": ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"],
        "prices": [0, 0, 0, 0, 0, 0],
        "currency": "ETB",
        "market_name": f"{country} {crop} Market",
    })


@dataclass
class RouteRecommendation:
    station_id: str
    station_name: str
    station_type: str
    distance_km: float
    base_cherry_price: float
    dividend_estimate: float
    spoilage_penalty: float
    net_yield: float


def _simulate_ocr_text(image_path: str) -> str:
    """Simulate OCR output from a photo path or a fallback text string."""
    if os.path.exists(image_path):
        try:
            with open(image_path, "r", encoding="utf-8") as reader:
                return reader.read().strip()
        except Exception:
            pass
    return image_path.strip()


def _parse_chalkboard_text(raw_text: str) -> Dict[str, Optional[Any]]:
    """Extract price and station hints from fallback chalkboard text."""
    price_match = re.search(r"price\s*[:\-]?\s*(\d+)", raw_text, re.IGNORECASE)
    station_hint = None

    if "agaro" in raw_text.lower() or "primary" in raw_text.lower():
        station_hint = "agaro_primary_coop"
    elif "kata" in raw_text.lower() or "muduga" in raw_text.lower():
        station_hint = "kata_muduga_mill"

    return {
        "price": int(price_match.group(1)) if price_match else None,
        "station_id": station_hint,
        "raw_text": raw_text,
    }


def process_chalkboard_photo(image_path: str, station_id: Optional[str] = None) -> Dict[str, Any]:
    """Simulate OCR ingestion and update the base cherry price in the in-memory DB."""
    raw_text = _simulate_ocr_text(image_path)
    parsed = _parse_chalkboard_text(raw_text)

    if parsed["price"] is None:
        raise ValueError(
            "Unable to parse price from chalkboard input. Provide text like 'Price: 230 ETB - Agaro'."
        )

    target_station_id = station_id or parsed["station_id"]
    if target_station_id is None:
        raise ValueError(
            "Station ID could not be inferred from the chalkboard text. Provide station_id explicitly."
        )

    if target_station_id not in STATION_DB:
        raise KeyError(f"Station '{target_station_id}' not found in station database.")

    old_price = STATION_DB[target_station_id]["base_cherry_price"]
    STATION_DB[target_station_id]["base_cherry_price"] = parsed["price"]

    return {
        "station_id": target_station_id,
        "station_name": STATION_DB[target_station_id]["station_name"],
        "old_price": old_price,
        "new_price": parsed["price"],
        "raw_text": raw_text,
    }


def _haversine_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in kilometers using the Haversine formula."""
    lat1_rad, lng1_rad, lat2_rad, lng2_rad = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2_rad - lat1_rad
    dlng = lng2_rad - lng1_rad
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    earth_km = 6371.0
    return earth_km * c


def calculate_best_route(
    farmer_lat: float,
    farmer_lng: float,
    weather_condition: str = "Clear",
    crop: str = "coffee",
) -> RouteRecommendation:
    """Compute the best net-yield station for a farmer near Jimma."""
    best: Optional[RouteRecommendation] = None

    # For demo purposes, prefer explicit crop->station mapping when available
    crop_station_map = {
        "coffee": ["agaro_primary_coop", "kata_muduga_mill"],
        "wheat": ["bale_agricultural_union_hub"],
        "teff": ["north_shewa_grain_center"],
    }

    stations_to_iterate = STATION_DB.items()
    mapped = crop_station_map.get((crop or "").lower())
    if mapped:
        stations_to_iterate = [(sid, STATION_DB[sid]) for sid in mapped if sid in STATION_DB]

    for station_id, station in stations_to_iterate:
        # If station declares `crops`, only consider it when the requested crop matches.
        station_crops = station.get("crops")
        if station_crops and (crop or "").lower() not in [c.lower() for c in station_crops]:
            continue
        distance_km = _haversine_distance_km(
            farmer_lat,
            farmer_lng,
            station["latitude"],
            station["longitude"],
        )

        # Compute transport cost and realistic net-yield math:
        # Net Yield = Base Price - (Distance * Transport Cost per km)
        # Keep spoilage_penalty and dividend_estimate as separate fields for guardrails/reporting.
        transport_cost = distance_km * TRANSPORT_COST_PER_KM
        spoilage_penalty = 0.0
        if weather_condition == "Heavy Rain" and distance_km > HEAVY_RAIN_DISTANCE_KM:
            spoilage_penalty = HEAVY_RAIN_SPOILAGE_PENALTY

        net_yield = station["base_cherry_price"] - transport_cost

        recommendation = RouteRecommendation(
            station_id=station_id,
            station_name=station["station_name"],
            station_type=station["station_type"],
            distance_km=round(distance_km, 2),
            base_cherry_price=float(station["base_cherry_price"]),
            dividend_estimate=float(station["dividend_estimate"]),
            spoilage_penalty=spoilage_penalty,
            net_yield=round(net_yield, 2),
        )

        if best is None or recommendation.net_yield > best.net_yield:
            best = recommendation

    if best is None:
        raise RuntimeError("No stations available to route to.")

    return best


def evaluate_guardrails_and_message(
    recommendation: RouteRecommendation,
    country: str = "Ethiopia",
    crop: str = "coffee",
    storage_type: Optional[str] = None,
    cash_need_level: Optional[str] = None,
    weather_condition: Optional[str] = None,
) -> Dict[str, str]:
    """Return a dict with `message` and `guardrail_status` tailored per crop and scenario."""
    crop_l = (crop or "").lower()

    # Scenario A: Wheat + Heavy Rain + Traditional Storage
    if crop_l == "wheat" and weather_condition == "Heavy Rain" and storage_type and "traditional" in storage_type.lower():
        base = recommendation.base_cherry_price
        net = recommendation.net_yield
        guard = "🚨 SPOILAGE RISK: Heavy rain vs Traditional storage alert"
        msg = (
            f"✅ HarvestBridge Alert [Wheat]: Heavy rain forecasted. High risk of mold in traditional storage. "
            f"Recommendation: Dispatch your wheat directly to the Bale Agricultural Union Hub within 48 hours. "
            f"Base Price: {base:.0f} ETB/Quintal. Estimated Net Yield (after transport): {net:.0f} ETB/Quintal."
        )
        return {"message": msg, "guardrail_status": guard}

    # Scenario B: Teff + Low Cash Urgency + Hermetic Storage
    if crop_l == "teff" and cash_need_level == "LOW" and storage_type and "hermetic" in storage_type.lower():
        base = recommendation.base_cherry_price
        net = recommendation.net_yield
        guard = "💎 SPECULATIVE HOLD: High profit optimization cleared"
        msg = (
            f"✅ HarvestBridge Alert [Teff]: Market trend indicates Teff prices will peak in 90 days. "
            f"Since your Hermetic Storage protects against pests and cash urgency is LOW, Recommendation: HOLD your crop. "
            f"Current Base Price: {base:.0f} ETB/Quintal. Estimated Net Yield: {net:.0f} ETB/Quintal."
        )
        return {"message": msg, "guardrail_status": guard}

    # Nigeria maize template
    if country == "Nigeria":
        storage_note = "Storage is Traditional Bags; watch for rapid post-harvest spoilage within 7 days."
        if storage_type and "hermetic" in storage_type.lower():
            storage_note = "Hermetic storage is available; spoilage risk is lower if handled correctly."

        urgency_note = ""
        if cash_need_level == "HIGH":
            urgency_note = " High cash urgency is detected; prioritize speedy sale."

        msg = (
            "✅ HarvestBridge Alert: Recommended Action for your Maize.\n"
            f"🏪 Hub: Ondo Grain Collection Center 📍 Distance: {recommendation.distance_km:.2f} km\n"
            f"💵 Base Price: {recommendation.base_cherry_price:.0f} NGN\n"
            f"📈 Estimated Net Yield: {recommendation.net_yield:.0f} NGN\n"
            f"⚠️ Note: {storage_note}{urgency_note}"
        )
        return {"message": msg, "guardrail_status": ""}

    # Default Ethiopia coffee template
    storage_note = "" if storage_type and "hermetic" in storage_type.lower() else "Note that traditional transport may increase handling risk."
    urgency_note = "" if cash_need_level != "HIGH" else " High cash urgency is detected; prioritize the nearest buyer."

    msg = (
        "✅ HarvestBridge Alert: Recommended Action for your Coffee Cherries.\n"
        f"🏪 Station: {recommendation.station_name} 📍 Distance: {recommendation.distance_km:.2f} km\n"
        f"💵 Base Price: {recommendation.base_cherry_price:.0f} ETB\n"
        f"📈 Estimated Net Yield (after transport): {recommendation.net_yield:.0f} ETB\n"
        "⚠️ Note: Cooperative payout includes standard historical union dividends. "
        f"{storage_note}{urgency_note}"
    )
    return {"message": msg, "guardrail_status": ""}


if FastAPI is not None:
    app = FastAPI(title="HarvestBridge Arbitrage Engine")

    class LocationCoordinates(BaseModel):
        lat: float
        lng: float

    class WhatsAppWebhookPayload(BaseModel):
        phone_number: str
        location_coordinates: LocationCoordinates
        weather_condition: Optional[str] = "Clear"
        country: str = "Ethiopia"
        crop: str = "coffee"
        storage_type: Optional[str] = None
        cash_need_level: Optional[str] = None
        market_available: bool = True
        market_status: str = "active_feed"

    @app.post("/whatsapp-webhook")
    def whatsapp_webhook(payload: WhatsAppWebhookPayload) -> Dict[str, Any]:
        historical = get_historical_market_trend(payload.country, payload.crop)
        recommendation = calculate_best_route(
            payload.location_coordinates.lat,
            payload.location_coordinates.lng,
            payload.weather_condition,
            crop=payload.crop,
        )

        result = evaluate_guardrails_and_message(
            recommendation,
            country=payload.country,
            crop=payload.crop,
            storage_type=payload.storage_type,
            cash_need_level=payload.cash_need_level,
            weather_condition=payload.weather_condition,
        )
        message = result.get("message", "")
        guardrail_status = result.get("guardrail_status", "")
        # Debug: print payload crop and chosen station
        print(f"WH webhook: crop={payload.crop} chosen_station={recommendation.station_id} distance={recommendation.distance_km} net={recommendation.net_yield}")
        return {
            "phone_number": payload.phone_number,
            "whatsapp_message": message,
            "market_status": payload.market_status,
            "market_available": payload.market_available,
            "market_name": historical["market_name"],
            "currency": historical["currency"],
            "historical_months": historical["months"],
            "historical_prices": historical["prices"],
            "recommended_station": {
                "station_id": recommendation.station_id,
                "station_name": recommendation.station_name,
                "distance_km": recommendation.distance_km,
                "net_yield": recommendation.net_yield,
            },
            "guardrail_status": guardrail_status,
        }
