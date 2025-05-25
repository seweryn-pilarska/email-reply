import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import Runnable
from langgraph.graph import StateGraph, END
from openai import OpenAI
import requests
import datetime
import json
from langsmith import traceable

load_dotenv(dotenv_path="config/.env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class GraphState(dict):
    pass

@traceable(name="IntentDetector")
def detect_intent_node(state: dict) -> dict:
    email = state["email"]
    prompt = prompt = f"""
Classify the intent of the following email:

"{email}"

Choose one:
- ScheduleMeeting
- RescheduleMeeting
- RequestUpdate
- ProvideUpdate
- Question
- Complaint
- Greeting
- Thanks
- FollowUp
- Cancellation
- TaskRequest
- TaskResponse
- OutOfOffice
- GeneralInfo
- Other

Respond with only the intent label.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )

    intent = response.choices[0].message.content.strip()
    return {"email": email, "intent": intent}

@traceable(name="ExtractMeetingInfo")
def extract_meeting_info_node(state: dict) -> dict:
    email_text = state["email"]
    today = datetime.date.today().isoformat()

    prompt = f"""
Today is {today}.

Extract the following fields from the email and return a valid JSON object only.

Email:
\"\"\"{email_text}\"\"\"

Output:
{{
  "summary": string,
  "attendee_email": string,
  "date": string (YYYY-MM-DD),
  "start_time": string (HH:MM),
  "end_time": string (HH:MM)
}}
Only return valid JSON with these exact keys and no extra explanation.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    raw_output = response.choices[0].message.content.strip()

    try:
        extracted = json.loads(raw_output)
        return {**state, **extracted}
    except Exception as e:
        return {**state, "reply": "Failed to extract meeting info. Please try rephrasing."}

@traceable(name="ScheduleAgent")
def schedule_meeting_node(state: dict) -> dict:
    start = f"{state['date']}T{state['start_time']}:00+02:00"
    end = f"{state['date']}T{state['end_time']}:00+02:00"

    payload = {
        "summary": state["summary"],
        "start": {
            "date": state["date"],
            "dateTime": start,
            "timeZone": "Europe/Warsaw"
        },
        "end": {
            "date": state["date"],
            "dateTime": end,
            "timeZone": "Europe/Warsaw"
        },
        "description": f"Created from message: {state['email']}",
        "location": "Google Meet",
        "attendees": [state["attendee_email"]],
        "recurrence": [],
        "reminders": {"useDefault": True, "overrides": []}
    }

    try:
        response = requests.post(
            "http://127.0.0.1:8000/calendars/primary/events",
            json=payload,
            params={"send_notifications": True}
        )

        if response.status_code == 201:
            result = response.json()
            reply = f"Meeting scheduled!\nSummary: {state['summary']}\nTime: {state['start_time']} on {state['date']}"
        else:
            reply = f"Failed to schedule meeting. Status: {response.status_code}"
    except Exception as e:
        reply = f"Exception during scheduling: {str(e)}"
    return {"reply": reply}

@traceable(name="ComplaintAgent")
def complaint_handler_node(state: dict) -> dict:
    email = state["email"]
    prompt = f"The user is upset. Write a professional, apologetic response.\nEmail: {email}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}]
    )
    reply = response.choices[0].message.content.strip()
    return {"reply": reply}

@traceable(name="DefaultReplyAgent")
def default_reply_node(state: dict) -> dict:
    email = state["email"]
    intent = state["intent"]
    prompt = f"Write a professional reply. Intent: {intent}\nEmail: {email}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}]
    )
    reply = response.choices[0].message.content.strip()
    return {"reply": reply}

@traceable(name="IntentRouter")
def route_by_intent(state: dict) -> str:
    intent = state.get("intent", "Other")

    if intent == "ScheduleMeeting":
        return "ExtractMeetingInfo"
    elif intent == "Complaint":
        return "ComplaintAgent"
    else:
        return "DefaultReplyAgent"

def build_agent_graph() -> Runnable:
    graph = StateGraph(dict)

    graph.add_node("IntentDetector", detect_intent_node)
    graph.add_node("IntentRouter", lambda x: x)
    graph.add_conditional_edges("IntentRouter", route_by_intent)

    graph.add_node("ExtractMeetingInfo", extract_meeting_info_node)
    graph.add_node("ScheduleAgent", schedule_meeting_node)
    graph.add_node("ComplaintAgent", complaint_handler_node)
    graph.add_node("DefaultReplyAgent", default_reply_node)

    graph.set_entry_point("IntentDetector")
    graph.add_edge("IntentDetector", "IntentRouter")

    graph.add_edge("ExtractMeetingInfo", "ScheduleAgent")
    graph.add_edge("ScheduleAgent", END)
    graph.add_edge("ComplaintAgent", END)
    graph.add_edge("DefaultReplyAgent", END)

    return graph.compile()