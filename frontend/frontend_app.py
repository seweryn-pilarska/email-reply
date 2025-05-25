import streamlit as st
import requests

API_URL = "http://127.0.0.1:5000/api/chat"

st.set_page_config(page_title="Email Reply Assistant", page_icon="✉️")
st.title("Email Reply Assistant")
st.markdown("##### Paste your email content below and click Generate Reply to get started.")

if "email_text" not in st.session_state:
    st.session_state.email_text = ""
if "reply_text" not in st.session_state:
    st.session_state.reply_text = ""

st.text_area(
    label="",
    key="email_text",
    height=200,
    placeholder="Paste your email here..."
)

if st.button("💡 Generate Reply"):
    if not st.session_state.email_text.strip():
        st.warning("Please enter a message first.")
    else:
        with st.spinner("Loading..."):
            try:
                response = requests.post(API_URL, json={"human_message": st.session_state.email_text})
                if response.status_code == 200:
                    st.session_state.reply_text = response.json()["response"]
                else:
                    st.error("Something went wrong. Try again.")
            except Exception as e:
                st.error(f"Error: {e}")

if st.session_state.reply_text:
    st.markdown("#### Suggested Reply")
    st.code(st.session_state.reply_text, language="text")

st.markdown("---")
st.caption("Built with LangGraph, Streamlit, and Google Calendar MCP for the Generative AI course project.")

