import os

import streamlit as st

import main

st.set_page_config(page_title="HarvestBridge Dashboard", page_icon="🌾", layout="wide")

st.title("🌾 HarvestBridge Operator Dashboard")
st.caption("Live market, weather, guardrail, and mobile dispatch preview for smallholder sales decisions.")

with st.sidebar:
    st.header("Operator Controls")
    country = st.selectbox("Country", ["Nigeria", "Ethiopia"], index=0)
    crop = st.selectbox("Crop Type", ["Maize", "Wheat", "Teff", "Yam"], index=0)
    storage = st.radio("Storage Type", ["Traditional open bags", "Hermetic storage"], index=0)
    cash_need_level = st.radio("Cash Urgency", ["LOW", "HIGH"], index=1)
    run = st.button("⚡ Run HarvestBridge Engine", use_container_width=True)

    st.markdown("---")
    st.caption("Tip: Use the live backend metrics panel to review market data, weather risk, and guardrail status before dispatch.")

col1, col2 = st.columns([1.1, 1.2])

with col1:
    st.subheader("Live Backend Metrics")
    if not run:
        st.info("Select your inputs in the sidebar and click the action button to generate a live recommendation.")
    else:
        with st.spinner("Running HarvestBridge engine..."):
            recommendation = main.process_farmer_inquiry(
                farmer_id="STREAMLIT_USER",
                location="Abia" if country == "Nigeria" else "Addis Ababa",
                crop=crop.lower(),
                harvest_volume="20 bags",
                storage_capability=storage,
                cash_need_level=cash_need_level,
                country=country,
            )

        market = main.load_market_prices("Abia" if country == "Nigeria" else "Addis Ababa", crop.lower(), country)
        weather = main.fetch_5day_forecast("Abia" if country == "Nigeria" else "Addis Ababa")
        guardrails = main.check_guardrails(
            {
                "cash_need_level": cash_need_level,
                "storage_capability": storage,
            },
            market,
            weather,
        )

        st.metric("Market", market["market_name"] if market else "Unavailable", f"{market['current_price']} {market['currency']}" if market else "")
        st.metric("5-Day Rainfall", f"{weather['day1_2']['rainfall_mm'] + weather['day3_5']['rainfall_mm']:.1f} mm" if weather else "Unavailable", f"Humidity {weather['day1_2']['humidity']:.0f}% / {weather['day3_5']['humidity']:.0f}%" if weather else "")

        st.markdown("**Guardrail Status**")
        if guardrails.get("forced_action"):
            st.error(f"Forced action: {guardrails['forced_action']}")
        else:
            st.success("No forced action required.")

        if guardrails.get("violations"):
            for item in guardrails["violations"]:
                st.warning(item)
        else:
            st.info("No critical guardrail violations detected.")

        st.markdown("---")
        st.markdown("**Generated Recommendation**")
        st.write(recommendation)

with col2:
    st.subheader("Mobile Dispatch Preview")
    channel = st.radio("Channel", ["WhatsApp", "SMS"], horizontal=True)

    if run:
        with st.spinner("Preparing dispatch preview..."):
            recommendation = main.process_farmer_inquiry(
                farmer_id="STREAMLIT_USER",
                location="Abia" if country == "Nigeria" else "Addis Ababa",
                crop=crop.lower(),
                harvest_volume="20 bags",
                storage_capability=storage,
                cash_need_level=cash_need_level,
                country=country,
            )

        if channel == "SMS":
            preview_text = recommendation[:160]
        else:
            preview_text = recommendation

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
