import streamlit as st
import requests

API_URL = "http://127.0.0.1:5000/api/chat"

st.set_page_config(page_title="AI Email Reply Generator")
st.title("AI Email Reply Generator")

email_text = st.text_area("Paste your message here:")

if st.button("Generate Reply"):
    if not email_text.strip():
        st.warning("Please paste an email to generate a reply.")
    else:
        with st.spinner("Loading..."):
            response = requests.post(API_URL, json={"human_message": email_text})
            if response.status_code == 200:
                reply = response.json()["response"]
                st.success("" \
                "Generated Reply:")
                st.write(reply)
            else:
                st.error("Failed to get the reply.")