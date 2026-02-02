"""
Voice Evaluation Backend with Supabase Integration
Fixed to use TEXT email column instead of UUID
Added endpoint to fetch by email + role
"""

import os
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Voice Evaluation API", version="2.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
VAPI_PUBLIC_KEY = os.getenv("VAPI_PUBLIC_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not VAPI_PUBLIC_KEY:
    raise ValueError("VAPI_PUBLIC_KEY required")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials required")

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================================================
# MODELS
# ============================================================================

class RoleInfo(BaseModel):
    id: str
    title: str
    description: str


class SessionRequest(BaseModel):
    role: str
    candidate_name: str = Field(min_length=1, max_length=100)
    user_email: str


class EvaluationReport(BaseModel):
    session_id: str
    candidate_name: str
    role: str
    timestamp: str
    duration_minutes: int
    
    score_1: int
    score_2: int
    score_3: int
    score_4: int
    score_5: int
    overall_score: float
    
    strength_1: str
    strength_2: str
    strength_3: str
    
    improvement_1: str
    improvement_2: str
    
    recommendation: str
    transcript: str


# ============================================================================
# IN-MEMORY STORAGE (temporary during call)
# ============================================================================

sessions: Dict[str, Dict] = {}
call_to_session: Dict[str, str] = {}
assistant_to_session: Dict[str, str] = {}

# ============================================================================
# ROLE CONFIGURATIONS
# ============================================================================

ROLES = {
    "project_manager": {
        "title": "Project Manager",
        "description": "Project delivery and team management evaluation",
        "assistant_id": os.getenv("ASSISTANT_ID_PROJECT_MANAGER"),
        "criteria": [
            "Problem Solving",
            "Leadership",
            "Communication",
            "Accountability",
            "Planning"
        ],
        "scenario": "We're 3 months behind schedule and 40% over budget on the Bangalore project. What happened and what's your plan?"
    },
    
    "team_lead": {
        "title": "Team Lead",
        "description": "Technical leadership and team management",
        "assistant_id": os.getenv("ASSISTANT_ID_TEAM_LEAD"),
        "criteria": [
            "Mentoring",
            "Technical Decisions",
            "Communication",
            "Conflict Resolution",
            "Process"
        ],
        "scenario": "Team velocity dropped 35% and two senior developers resigned. What's happening?"
    },
    
    "product_owner": {
        "title": "Product Owner",
        "description": "Product strategy and stakeholder management",
        "assistant_id": os.getenv("ASSISTANT_ID_PRODUCT_OWNER"),
        "criteria": [
            "Strategy",
            "Data-Driven",
            "Stakeholders",
            "User Focus",
            "Prioritization"
        ],
        "scenario": "Last 3 features failed adoption targets and churn is up 15%. Explain your strategy."
    },
    
    "sales_manager": {
        "title": "Sales Manager",
        "description": "Sales performance and team coaching",
        "assistant_id": os.getenv("ASSISTANT_ID_SALES_MANAGER"),
        "criteria": [
            "Sales Skills",
            "Coaching",
            "Accounts",
            "Forecasting",
            "Pressure"
        ],
        "scenario": "Missed quota by 30%, pipeline at 1.5x instead of 3x, three accounts at risk. What's your plan?"
    }
}

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/")
def root():
    return {"status": "running", "version": "2.2.0"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "vapi_configured": bool(VAPI_PUBLIC_KEY),
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY)
    }


@app.get("/roles", response_model=List[RoleInfo])
def get_roles():
    return [
        RoleInfo(id=k, title=v["title"], description=v["description"])
        for k, v in ROLES.items()
        if v.get("assistant_id")
    ]


@app.post("/session/start")
def start_session(req: SessionRequest):
    if req.role not in ROLES:
        raise HTTPException(400, "Invalid role")
    
    role = ROLES[req.role]
    if not role.get("assistant_id"):
        raise HTTPException(503, "Assistant not configured")
    
    # Validate email format
    if "@" not in req.user_email:
        raise HTTPException(400, "Invalid email address")
    
    # Create session ID
    timestamp = int(datetime.now().timestamp() * 1000)
    session_id = f"session_{req.role}_{timestamp}"
    
    assistant_id = role["assistant_id"]
    
    # Store with email
    sessions[session_id] = {
        "session_id": session_id,
        "role": req.role,
        "role_title": role["title"],
        "candidate": req.candidate_name,
        "criteria": role["criteria"],
        "assistant_id": assistant_id,
        "user_email": req.user_email,
        "started": datetime.now().isoformat()
    }
    
    # Map assistant to session
    assistant_to_session[assistant_id] = session_id
    
    logger.info(f"✅ Session created: {session_id}")
    logger.info(f"   User Email: {req.user_email}")
    logger.info(f"   Candidate: {req.candidate_name}")
    logger.info(f"   Role: {role['title']}")
    logger.info(f"   Assistant ID: {assistant_id}")
    
    return {
        "success": True,
        "sessionId": session_id,
        "publicKey": VAPI_PUBLIC_KEY,
        "assistantId": assistant_id,
        "scenario": role["scenario"]
    }


@app.post("/webhook/vapi")
async def vapi_webhook(request: Request):
    try:
        payload = await request.json()
        message = payload.get("message", {})
        event = message.get("type") or payload.get("type")
        
        logger.info(f"📥 RECEIVED EVENT: {event}")

        if event == "assistant-request":
            call_id = message.get("call", {}).get("id")
            assistant_id = message.get("assistantId") or message.get("assistant", {}).get("id")
            session_id = assistant_to_session.get(assistant_id)
            if session_id:
                call_to_session[call_id] = session_id
                logger.info(f"🔗 Mapped Call {call_id} -> Session {session_id}")
            return {"status": "ok"}

        elif event == "end-of-call-report":
            logger.info("📊 Processing Final Report...")
            logger.info(f"Full payload keys: {payload.keys()}")
            logger.info(f"Message keys: {message.keys()}")
            
            call_data = message.get("call", {})
            call_id = call_data.get("id")
            
            session_id = call_to_session.get(call_id) or (list(sessions.keys())[-1] if sessions else None)
            
            if not session_id or session_id not in sessions:
                logger.error("❌ No session metadata found.")
                logger.error(f"   Call ID: {call_id}")
                logger.error(f"   Available sessions: {list(sessions.keys())}")
                return {"status": "error", "message": "session not found"}

            session = sessions[session_id]
            transcript = message.get("transcript", "No transcript available")

            # --- DYNAMIC EXTRACTION OF SCORES ---
            artifact = message.get("artifact", {})
            structured_outputs = artifact.get("structuredOutputs", {})
            
            structured = {}
            if structured_outputs:
                first_output = list(structured_outputs.values())[0]
                structured = first_output.get("result", {})
                logger.info(f"✅ Found AI Scores: {structured}")
            else:
                # Fallback
                structured = message.get("analysis", {}).get("structuredData", {})
                logger.info(f"⚠️ Using fallback structured data: {structured}")

            # Calculate duration
            start = call_data.get("startedAt")
            end = call_data.get("endedAt")
            duration_min = max(1, (iso_to_ms(end) - iso_to_ms(start)) // 60000) if start and end else 1

            # --- PREPARE DATABASE PAYLOAD ---
            db_data = {
                "session_id": session_id,
                "user_email": session["user_email"],
                "candidate_name": session["candidate"],
                "role": session["role_title"],
                "duration_minutes": duration_min,
                "overall_score": float(structured.get("overall", 0)),
                "recommendation": str(structured.get("rec", "N/A"))[:500],
                "transcript": transcript[:3000],
                "score_1": int(structured.get("s1", 0)),
                "score_2": int(structured.get("s2", 0)),
                "score_3": int(structured.get("s3", 0)),
                "score_4": int(structured.get("s4", 0)),
                "score_5": int(structured.get("s5", 0)),
                "strength_1": str(structured.get("str1", "N/A"))[:500],
                "strength_2": str(structured.get("str2", "N/A"))[:500],
                "strength_3": str(structured.get("str3", "N/A"))[:500],
                "improvement_1": str(structured.get("imp1", "N/A"))[:500],
                "improvement_2": str(structured.get("imp2", "N/A"))[:500]
            }

            logger.info(f"💾 Saving to Supabase:")
            logger.info(f"   Session: {session_id}")
            logger.info(f"   User Email: {session['user_email']}")
            logger.info(f"   Candidate: {session['candidate']}")
            logger.info(f"   Overall Score: {db_data['overall_score']}")

            try:
                result = supabase.table("evaluations").insert(db_data).execute()
                logger.info(f"🚀 SUCCESS: Saved to Supabase!")
                logger.info(f"   Inserted record with session_id: {session_id}")
            except Exception as e:
                logger.error(f"❌ Supabase Insert Failed: {e}")
                logger.error(f"   Error type: {type(e).__name__}")
                logger.error(f"   Data attempted: {db_data}")
                return {"status": "error", "message": str(e)}

            # Cleanup
            sessions.pop(session_id, None)
            call_to_session.pop(call_id, None)
            
            logger.info(f"✅ Webhook processing complete for session {session_id}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"🔥 Webhook Crash: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

def iso_to_ms(iso_str):
    """Helper to convert Vapi ISO timestamps to milliseconds"""
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return int(dt.timestamp() * 1000)
    except: 
        return 0


@app.get("/evaluations/{user_email}")
def get_user_evaluations(user_email: str):
    """Get all evaluations for a user by email"""
    try:
        logger.info(f"📊 Fetching all evaluations for user: {user_email}")
        
        result = supabase.table("evaluations")\
            .select("*")\
            .eq("user_email", user_email)\
            .order("created_at", desc=True)\
            .execute()
        
        logger.info(f"✅ Found {len(result.data)} evaluations")
        return {"evaluations": result.data}
    except Exception as e:
        logger.error(f"❌ Error fetching evaluations: {e}")
        raise HTTPException(500, f"Failed to fetch evaluations: {str(e)}")


@app.get("/evaluations/{user_email}/role/{role}")
def get_user_evaluations_by_role(user_email: str, role: str):
    """Get evaluations for a specific user and role"""
    try:
        logger.info(f"📊 Fetching evaluations for user: {user_email}, role: {role}")
        
        # Get role title
        role_title = ROLES.get(role, {}).get("title", role)
        
        result = supabase.table("evaluations")\
            .select("*")\
            .eq("user_email", user_email)\
            .eq("role", role_title)\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()
        
        logger.info(f"✅ Found {len(result.data)} evaluations for role: {role_title}")
        return {"evaluations": result.data}
    except Exception as e:
        logger.error(f"❌ Error fetching evaluations: {e}")
        raise HTTPException(500, f"Failed to fetch evaluations: {str(e)}")


@app.get("/evaluation/{session_id}")
def get_evaluation(session_id: str):
    """Get specific evaluation by session ID"""
    try:
        logger.info(f"🔍 Fetching evaluation for session: {session_id}")
        
        result = supabase.table("evaluations")\
            .select("*")\
            .eq("session_id", session_id)\
            .execute()
        
        if not result.data:
            logger.warning(f"⚠️ Evaluation not found: {session_id}")
            raise HTTPException(404, f"Evaluation not found: {session_id}")
        
        logger.info(f"✅ Evaluation found: {result.data[0].get('candidate_name')}")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching evaluation: {e}")
        raise HTTPException(500, f"Failed to fetch evaluation: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)