"""
supervisor/graph.py
Pure LangGraph core   NO MCP server, NO main(), NO port binding.

Responsibilities:
    All system prompts (Supervisor + 7 specialist agents + direct answering fallback)
    EduState TypedDict
    build_graph()   compiles the LangGraph with all specialist agents + fallback
    serialise_messages()   LangChain msg objects → JSON-safe dicts
    build_trace()   routing trace for the Streamlit UI trace panel

Imported by supervisor_server.py (FastMCP port 9001).
"""

import sys
import os
import asyncio
import logging
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nest_asyncio
from dotenv import load_dotenv
from typing import Annotated, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage, ToolMessage, HumanMessage,
)
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_mcp_adapters.client import MultiServerMCPClient

nest_asyncio.apply()
load_dotenv()

log = logging.getLogger(__name__)

#   Specialist MCP server URLs                        
SPECIALIST_SERVERS = {
    "registration": {"transport": "streamable_http", "url": "http://127.0.0.1:8001/mcp", "timeout": timedelta(seconds=8)},
    "course":       {"transport": "streamable_http", "url": "http://127.0.0.1:8002/mcp", "timeout": timedelta(seconds=8)},
    "enrollment":   {"transport": "streamable_http", "url": "http://127.0.0.1:8003/mcp", "timeout": timedelta(seconds=8)},
    "grade":        {"transport": "streamable_http", "url": "http://127.0.0.1:8004/mcp", "timeout": timedelta(seconds=8)},
    "advising":     {"transport": "streamable_http", "url": "http://127.0.0.1:8005/mcp", "timeout": timedelta(seconds=8)},
    "fee":          {"transport": "streamable_http", "url": "http://127.0.0.1:8006/mcp", "timeout": timedelta(seconds=8)},
    "timetable":    {"transport": "streamable_http", "url": "http://127.0.0.1:8007/mcp", "timeout": timedelta(seconds=8)},
}

#  System prompts 
SUPERVISOR_PROMPT = """You are the EduManage AI Supervisor.

Your only job is routing: choose EXACTLY ONE best agent for each user request.

AGENT ROLES:
1. reg_agent: For NEW student registration, profile updates, and student search. 
   - USE THIS for: "Register a new student", "Create student profile", "Update student email".
2. course_agent: For course creation, catalog management, and course statistics.
3. enroll_agent: For existing students enrolling in or dropping courses.
   - NOTE: Do NOT use for REGISTERING new students. Only for ENROLLING them in classes.
4. grade_agent: For submitting grades and GPAs.
5. advising_agent: For degree audits and academic warnings.
6. fee_agent: For tuition fees and scholarships.
7. timetable_agent: For scheduling and room assignments.
8. direct_answering_agent: For general university policy questions.

Do not answer the user directly.
If uncertain, choose direct_answering_agent.
"""

REGISTRATION_PROMPT = """You are the Student Registration Specialist for EduManage AI.
Handle: new student registration, profile management, student ID assignment, status changes,
student search, department rosters, and admission statistics.
- Always auto-assign a student ID in format STU-YYYY-NNNN.
- Send a welcome email on every new registration.
- For status changes (suspension, graduation), confirm the action clearly.
- Show student statistics with counts by department and gender."""

COURSE_PROMPT = """You are the Course Management Specialist for EduManage AI.
Handle: creating/updating courses, course catalogue, seat capacity, waitlists,
opening/closing courses, and enrollment statistics.
- Always show current enrollment vs capacity (e.g., 24/30 seats).
- For full courses, proactively suggest adding student to waitlist.
- When opening a closed course, notify all waitlisted students by email.
- Show popular courses by fill percentage."""

ENROLLMENT_PROMPT = """You are the Enrollment Specialist for EduManage AI.
Handle: enrolling students in courses, dropping courses, schedule display,
prerequisite checks, enrollment history, bulk enrollment, course rosters.
- ALWAYS check prerequisites before enrolling.
- ALWAYS check the credit limit (max 21 credits per semester).
- Send confirmation email for every enrollment and drop.
- For capacity conflicts, suggest waitlist as an alternative.
- Show the full weekly schedule when displaying a student's courses."""

GRADE_PROMPT = """You are the Grade & Transcript Specialist for EduManage AI.
Handle: grade submission, GPA calculation, transcript generation, grade appeals,
grade distribution, grade updates, and academic standing determination.
- Valid grades: A, A-, B+, B, B-, C+, C, C-, D, F, I
- Always recalculate and update cumulative GPA after every grade change.
- Send email notification to student for every grade posted.
- For transcripts, show all semesters in chronological order.
- Determine and clearly state academic standing with every GPA check."""

ADVISING_PROMPT = """You are the Academic Advising Specialist for EduManage AI.
Handle: degree audits, at-risk student identification, advising appointments,
credit summaries, academic warnings, graduation eligibility, and study plans.
- For at-risk students (GPA < 2.0), always recommend booking an appointment.
- Send academic warning emails proactively for students on probation.
- Show degree completion percentage in every degree audit.
- Generate semester-by-semester study plans when requested.
- Book appointments by sending confirmation emails to BOTH student and advisor."""

FEE_PROMPT = """You are the Fee & Scholarship Specialist for EduManage AI.
Handle: tuition fee posting, payment recording, financial statements,
scholarship awards, scholarship eligibility checks, fee reminders.
- Always show outstanding balance in financial statements.
- Send payment receipt email for every payment recorded.
- Check scholarship eligibility before awarding   GPA and credit requirements matter.
- Send fee reminders for all unpaid/overdue fees when requested.
- Present financial data in  (Indian Rupees) format."""

TIMETABLE_PROMPT = """You are the Timetable & Scheduling Specialist for EduManage AI.
Handle: creating timetable slots, room assignment, faculty timetables,
student timetables, conflict detection, slot updates, schedule notifications.
- ALWAYS run conflict detection after any room or time change.
- Show timetable in day-by-day format (Monday through Saturday).
- Notify all enrolled students by email when a schedule changes.
- For room conflicts, clearly name both conflicting courses.
- Show time in HH:MM–HH:MM format."""

DIRECT_ANSWERING_PROMPT = """You are the Direct Answering Specialist for EduManage AI   the DEFAULT FALLBACK.

You answer ANY question related to student enrollment and course management using your knowledge:
  - University policies and procedures
  - How to enroll in a course, drop a course, appeal a grade
  - GPA calculation methods and academic standing rules
  - Credit hour requirements and course load limits
  - Scholarship application processes
  - Academic calendar and registration deadlines
  - Graduation requirements and degree audit
  - Transfer credit policies
  - Any other education-related question

STRICTLY limit yourself to Student Enrollment & Course Management topics.
If the question is completely unrelated to education (e.g., cooking, finance, sports), politely explain 
that you can only assist with student enrollment and course management questions.

You do NOT need any tools   answer directly from your knowledge.
Always be helpful, clear, and student-friendly."""

def _make_agent(llm, tools, prompt):
    return create_agent(model=llm, tools=tools, system_prompt=prompt)


class EduState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    route: str


class RouteDecision(BaseModel):
    route: Literal[
        "reg_agent",
        "course_agent",
        "enroll_agent",
        "grade_agent",
        "advising_agent",
        "fee_agent",
        "timetable_agent",
        "direct_answering_agent",
    ] = Field(description="Selected target agent node. Use reg_agent for ALL new student registrations.")
    reason: str = Field(description="Detailed reason for routing choice.")


#  Graph builder 
async def build_graph():
    """Build and compile the LangGraph supervisor. Called fresh per request."""
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60")),
    )
    client = MultiServerMCPClient(SPECIALIST_SERVERS)

    server_tools: dict[str, list] = {}
    all_tools: list = []
    for server_name in SPECIALIST_SERVERS:
        try:
            tools = await client.get_tools(server_name=server_name)
            server_tools[server_name] = tools
            all_tools.extend(tools)
            log.info("Loaded %d tool(s) from %s", len(tools), server_name)
        except Exception as exc:
            server_tools[server_name] = []
            log.warning("Failed loading tools from %s: %s", server_name, exc)

    def _match(tools, *keywords):
        matched = [t for t in tools if any(k in t.name.lower() for k in keywords)]
        return matched if matched else tools

    reg_tools = server_tools.get("registration") or _match(all_tools, "register_student", "get_student", "update_student", "search_student", "change_enrollment", "department_roster", "welcome_email", "student_stat")
    course_tools = server_tools.get("course") or _match(all_tools, "create_course", "update_course", "get_course", "list_course", "set_course", "waitlist", "enrollment_stat")
    enroll_tools = server_tools.get("enrollment") or _match(all_tools, "enroll_student", "drop_course", "student_schedule", "check_prereq", "enrollment_history", "bulk_enroll", "course_roster", "enrollment_confirm")
    grade_tools = server_tools.get("grade") or _match(all_tools, "submit_grade", "student_grade", "calculate_gpa", "generate_transcript", "grade_appeal", "grade_distribution", "update_grade", "academic_standing")
    advising_tools = server_tools.get("advising") or _match(all_tools, "degree_audit", "at_risk", "advising_appointment", "get_advising", "credit_summary", "academic_warning", "graduation", "study_plan")
    fee_tools = server_tools.get("fee") or _match(all_tools, "tuition_fee", "record_payment", "financial_statement", "scholarship", "fee_reminder", "financial_summary")
    timetable_tools = server_tools.get("timetable") or _match(all_tools, "timetable_slot", "assign_room", "faculty_timetable", "student_timetable", "detect_conflict", "update_slot", "room_availability", "schedule_notification")

    reg_agent = _make_agent(llm, reg_tools, REGISTRATION_PROMPT)
    course_agent = _make_agent(llm, course_tools, COURSE_PROMPT)
    enroll_agent = _make_agent(llm, enroll_tools, ENROLLMENT_PROMPT)
    grade_agent = _make_agent(llm, grade_tools, GRADE_PROMPT)
    advising_agent = _make_agent(llm, advising_tools, ADVISING_PROMPT)
    fee_agent = _make_agent(llm, fee_tools, FEE_PROMPT)
    timetable_agent = _make_agent(llm, timetable_tools, TIMETABLE_PROMPT)
    direct_answering_agent = _make_agent(llm, [], DIRECT_ANSWERING_PROMPT)

    def _latest_user_text(msgs: list) -> str:
        for msg in reversed(msgs):
            if isinstance(msg, HumanMessage):
                return str(msg.content)
        return ""

    def supervisor_agent(state: EduState):
        user_text = _latest_user_text(state.get("messages", []))
        try:
            router = llm.with_structured_output(RouteDecision)
            decision = router.invoke(
                [
                    {"role": "system", "content": SUPERVISOR_PROMPT},
                    {"role": "user", "content": user_text},
                ]
            )
            route = decision.route
            reason = decision.reason
        except Exception as exc:
            route = "direct_answering_agent"
            reason = f"Fallback due to routing error: {exc}"
        return {
            "route": route,
            "messages": [
                AIMessage(content=f"Routing to {route.replace('_', ' ')} ({reason})")
            ]
        }

    def _route(state: EduState) -> str:
        return state.get("route", "direct_answering_agent")

    graph = StateGraph(EduState)
    graph.add_node("supervisor", supervisor_agent)
    graph.add_node("reg_agent", reg_agent)
    graph.add_node("course_agent", course_agent)
    graph.add_node("enroll_agent", enroll_agent)
    graph.add_node("grade_agent", grade_agent)
    graph.add_node("advising_agent", advising_agent)
    graph.add_node("fee_agent", fee_agent)
    graph.add_node("timetable_agent", timetable_agent)
    graph.add_node("direct_answering_agent", direct_answering_agent)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route,
        {
            "reg_agent": "reg_agent",
            "course_agent": "course_agent",
            "enroll_agent": "enroll_agent",
            "grade_agent": "grade_agent",
            "advising_agent": "advising_agent",
            "fee_agent": "fee_agent",
            "timetable_agent": "timetable_agent",
            "direct_answering_agent": "direct_answering_agent",
            END: END,
        },
    )
    for node in [
        "reg_agent",
        "course_agent",
        "enroll_agent",
        "grade_agent",
        "advising_agent",
        "fee_agent",
        "timetable_agent",
        "direct_answering_agent",
    ]:
        graph.add_edge(node, END)

    return graph.compile()

#  Helpers 
def serialise_messages(msgs: list) -> list:
    out = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "human", "content": str(m.content)})
        elif isinstance(m, AIMessage):
            out.append({"role": "ai", "content": str(m.content),
                        "tool_calls": getattr(m, "tool_calls", []) or []})
        elif isinstance(m, ToolMessage):
            out.append({"role": "tool", "name": getattr(m, "name", ""),
                        "content": str(m.content),
                        "tool_call_id": getattr(m, "tool_call_id", "")})
    return out


def build_trace(msgs: list) -> list:
    # Find the last HumanMessage index to trace only the latest turn.
    last_user_idx = 0
    for i, m in enumerate(msgs):
        if isinstance(m, HumanMessage):
            last_user_idx = i

    current_turn_msgs = msgs[last_user_idx:]

    trace = []
    for message_index, m in enumerate(current_turn_msgs, start=1):
        if isinstance(m, AIMessage):
            calls = getattr(m, "tool_calls", None) or []
            text = str(m.content or "")
            if text.lower().startswith("routing to "):
                trace.append(
                    {
                        "type": "tool_call",
                        "label": f"Routing: {text}",
                        "message_index": message_index,
                        "message_role": "assistant",
                    }
                )
                continue
            for tc in calls:
                name = tc.get("name", "")
                label = (
                    "Routed to "
                    + name.replace("transfer_to_", "").replace("_", " ").title()
                    if "transfer_to_" in name
                    else f"Called: {name}"
                )
                trace.append(
                    {
                        "type": "tool_call",
                        "label": label,
                        "tool": name,
                        "message_index": message_index,
                        "message_role": "assistant",
                    }
                )
            if m.content and not calls:
                trace.append(
                    {
                        "type": "reply",
                        "label": f"Final reply ({len(str(m.content))} chars)",
                        "message_index": message_index,
                        "message_role": "assistant",
                    }
                )
        elif isinstance(m, ToolMessage):
            preview = str(m.content)[:80].replace("\\n", " ")
            trace.append(
                {
                    "type": "tool_result",
                    "label": f"Result: {preview}...",
                    "message_index": message_index,
                    "message_role": "tool",
                }
            )
    return trace

