import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import Runnable
from langgraph.graph import StateGraph, END
from openai import OpenAI

load_dotenv(dotenv_path="config/.env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class GraphState(dict):
    pass

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
    # print("Detected intent:")
    return {"email": email, "intent": intent}

def schedule_meeting_node(state: dict) -> dict:
    email = state["email"]
    prompt = f"Generate a polite response to schedule a meeting.\nEmail: {email}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}]
    )
    reply = response.choices[0].message.content.strip()
    return {"reply": reply}

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

def route_by_intent(state: dict) -> str:
    intent = state.get("intent", "Other")
    # print("Routing intent:")

    if intent == "ScheduleMeeting":
        return "ScheduleAgent"
    elif intent == "Complaint":
        return "ComplaintAgent"
    else:
        return "DefaultReplyAgent"

def build_agent_graph() -> Runnable:
    graph = StateGraph(dict)

    graph.add_node("IntentDetector", detect_intent_node)
    graph.add_node("IntentRouter", lambda x: x)  
    graph.add_conditional_edges("IntentRouter", route_by_intent)

    graph.add_node("ScheduleAgent", schedule_meeting_node)
    graph.add_node("ComplaintAgent", complaint_handler_node)
    graph.add_node("DefaultReplyAgent", default_reply_node)

    graph.set_entry_point("IntentDetector")
    graph.add_edge("IntentDetector", "IntentRouter")

    graph.add_edge("ScheduleAgent", END)
    graph.add_edge("ComplaintAgent", END)
    graph.add_edge("DefaultReplyAgent", END)

    return graph.compile()



