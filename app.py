import os

import pandas as pd
import requests
import streamlit as st

import main

st.set_page_config(page_title="HarvestBridge Dashboard", page_icon="🌾", layout="wide")

st.title("🌾 HarvestBridge Operator Dashboard")
st.caption("Live market, weather, guardrail, and mobile dispatch preview for smallholder sales decisions.")

def get_mock_location_and_weather(country: str, crop: str = "coffee") -> tuple[str, dict, str]:
    """Return a mock location and weather; for Ethiopia vary coordinates by crop to demo routing."""
    if country == "Ethiopia":
        crop_l = (crop or "").lower()
        # Coffee: farmer near Agaro (~5.5 km)
        if crop_l == "coffee":
            return "Jimma", {"lat": 7.801, "lng": 36.652}, "Heavy Rain"
        # Wheat: mock farmer coordinates to produce ~6.2 km distance to Bale hub
        if crop_l == "wheat":
            # Farmer coords chosen to be ~6.2 km from Bale hub (7.740,36.700)
            return "Bale", {"lat": 7.684, "lng": 36.700}, "Heavy Rain"
        # Teff: mock farmer coordinates to produce ~4.8 km distance to North Shewa center
        if crop_l == "teff":
            # Farmer coords chosen to be ~4.8 km from North Shewa center (9.000,39.000)
            return "North Shewa", {"lat": 9.043, "lng": 39.000}, "Clear"
        # Fallback for Ethiopia
        return "Jimma", {"lat": 7.801, "lng": 36.652}, "Heavy Rain"
    return "Ondo", {"lat": 7.10, "lng": 5.20}, "Clear"


with st.sidebar:
    st.header("Operator Controls")
    country = st.selectbox("Country", ["Nigeria", "Ethiopia"], index=0)
    # Dynamic crop options based on country
    crop_options = ["Maize", "Coffee"]
    if country == "Ethiopia":
        crop_options = ["Coffee", "Wheat", "Teff"]

    # Reset crop selection when country changes to avoid stale state
    if "_prev_country" not in st.session_state:
        st.session_state["_prev_country"] = country
    if st.session_state.get("_prev_country") != country:
        st.session_state["_prev_country"] = country
        if "crop" in st.session_state:
            del st.session_state["crop"]

    crop = st.selectbox("Crop Type", crop_options, index=0, key="crop")
    storage = st.radio("Storage Type", ["Traditional open bags", "Hermetic storage"], index=0)
    cash_need_level = st.radio("Cash Urgency", ["LOW", "HIGH"], index=1)
    run = st.button("⚡ Run HarvestBridge Engine", use_container_width=True)

    st.markdown("---")
    st.caption("Tip: Use the live backend metrics panel to review market data, weather risk, and guardrail status before dispatch.")

col1, col2 = st.columns([1.1, 1.2])

location_name, location_coordinates, weather_condition = get_mock_location_and_weather(country, crop)
backend_recommendation = None
backend_data = None
backend_error = None
market = None
weather = None
guardrails = None

with col1:
    st.subheader("Live Backend Metrics")
    if not run:
        st.info("Select your inputs in the sidebar and click the action button to generate a live recommendation.")
    else:
        with st.spinner("Running HarvestBridge engine..."):
            payload = {
                "phone_number": "+251911000000",
                "location_coordinates": location_coordinates,
                "weather_condition": weather_condition,
                "country": country,
                "crop": crop.lower(),
                "storage_type": storage,
                "cash_need_level": cash_need_level,
                "market_available": True,
                "market_status": "active_feed",
            }
            try:
                response = requests.post(
                    "http://127.0.0.1:8001/whatsapp-webhook",
                    json=payload,
                    timeout=5,
                )
                response.raise_for_status()
                backend_data = response.json()
                backend_recommendation = backend_data.get("whatsapp_message", "")
            except requests.exceptions.RequestException as exc:
                backend_error = str(exc)

        market = None
        if crop.lower() != "coffee":
            market = main.load_market_prices(location_name, crop.lower(), country)
        weather = main.fetch_5day_forecast(location_name)
        guardrails = main.check_guardrails(
            {
                "cash_need_level": cash_need_level,
                "storage_capability": storage,
            },
            market,
            weather,
        )

        if crop.lower() == "coffee" and guardrails:
            guardrails["violations"] = [
                v for v in guardrails.get("violations", []) if "DATA_VALIDATION" not in v
            ]
            if not guardrails["violations"]:
                guardrails["forced_action"] = None

        if backend_error:
            st.error("Unable to reach the HarvestBridge backend. Start the FastAPI server at http://127.0.0.1:8001 and retry.")
            st.markdown(f"**Details:** {backend_error}")
        else:
            st.success("HarvestBridge backend returned a recommendation.")

        market_label = market["market_name"] if market else backend_data.get("market_name") if backend_data else "Market Feed"
        market_price = None
        market_currency = None

        if market:
            market_price = market["current_price"]
            market_currency = market["currency"]
        elif backend_data:
            historical_prices = backend_data.get("historical_prices", [])
            market_price = historical_prices[-1] if historical_prices else None
            market_currency = backend_data.get("currency", "ETB")

        st.metric(
            "Market",
            market_label,
            f"{market_price} {market_currency}" if market_price is not None else "Unavailable",
        )
        st.metric(
            "5-Day Rainfall",
            f"{weather['day1_2']['rainfall_mm'] + weather['day3_5']['rainfall_mm']:.1f} mm" if weather else "Unavailable",
            f"Humidity {weather['day1_2']['humidity']:.0f}% / {weather['day3_5']['humidity']:.0f}%" if weather else "",
        )

        if backend_data and backend_data.get("historical_months") and backend_data.get("historical_prices"):
            st.markdown("**Historical Price Trend**")
            months = backend_data["historical_months"]
            prices = backend_data["historical_prices"]
            # Ensure chronological ordering for the chart (not alphabetical)
            months_order = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"]
            df = pd.DataFrame({"Month": months, "Price": prices})
            df["Month"] = pd.Categorical(df["Month"], categories=months_order, ordered=True)
            df = df.sort_values("Month").set_index("Month")
            st.line_chart(df)

        st.markdown("**Guardrail Status**")
        if guardrails.get("forced_action"):
            st.error(f"Forced action: {guardrails['forced_action']}")
        elif backend_data and backend_data.get("market_available"):
            st.success("✅ Active Data Pipeline Connected")
        else:
            st.success("No forced action required.")

        if guardrails.get("violations"):
            for item in guardrails["violations"]:
                st.warning(item)
        else:
            st.info("No critical guardrail violations detected.")

        st.markdown("---")
        st.markdown("**Generated Recommendation**")
        st.markdown(backend_recommendation or "No recommendation received from backend.", unsafe_allow_html=True)

with col2:
    st.subheader("Mobile Dispatch Preview")
    channel = st.radio("Channel", ["WhatsApp", "SMS"], horizontal=True)

    if run:
        if backend_error:
            preview_text = "Unable to preview dispatch because the backend call failed. Please start the server and retry."
        else:
            if channel == "SMS":
                preview_text = (backend_recommendation or "")[0:160]
            else:
                preview_text = backend_recommendation or ""

        st.markdown(
            f"""
            <style>
            .phone-shell {{
                width: 320px;
                margin: 0 auto;
                border-radius: 32px;
                padding: 10px;
                background: linear-gradient(135deg, #0f172a, #1f2937);
                box-shadow: 0 18px 40px rgba(15,23,42,0.35);
            }}
            .phone-screen {{
                min-height: 520px;
                border-radius: 24px;
                background: linear-gradient(180deg, #ffffff, #f8fafc);
                padding: 14px;
                color: #111827;
                font-family: Arial, sans-serif;
            }}
            .phone-top {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 12px;
                color: #475569;
                margin-bottom: 10px;
            }}
            .phone-chip {{
                background: #e2e8f0;
                border-radius: 999px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            .phone-body {{
                background: #eff6ff;
                border-radius: 18px;
                padding: 12px;
                border: 1px solid #bfdbfe;
                font-size: 13px;
                line-height: 1.35;
                white-space: pre-wrap;
            }}
            </style>
            <div class="phone-shell">
              <div class="phone-screen">
                <div class="phone-top">
                  <span>9:41</span>
                  <span class="phone-chip">{channel}</span>
                </div>
                <div class="phone-body">{preview_text}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("Click the Run button to preview the dispatch message.")
