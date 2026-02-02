"""
A2A Agent Registry - MVP

A public directory for A2A-compatible agents.
Fills the gap in the A2A spec for curated registry discovery.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
import uuid
import json

app = FastAPI(
    title="A2A Agent Registry",
    description="A public directory for discovering A2A-compatible agents",
    version="0.1.0",
)

# CORS for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Models ============

class AgentSkill(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: list[str] = []
    examples: list[str] = []


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False


class AgentCard(BaseModel):
    name: str
    description: str
    url: HttpUrl
    version: Optional[str] = None
    default_input_modes: list[str] = ["text"]
    default_output_modes: list[str] = ["text"]
    capabilities: Optional[AgentCapabilities] = None
    skills: list[AgentSkill] = []


class RegisteredAgent(BaseModel):
    id: str
    card: AgentCard
    registered_at: datetime
    last_seen: Optional[datetime] = None
    verified: bool = False  # Has the endpoint been verified?


class RegisterRequest(BaseModel):
    card: AgentCard


class RegisterResponse(BaseModel):
    success: bool
    agent_id: str
    message: str


# ============ In-Memory Store (MVP) ============

# In production, this would be a database
agents_db: dict[str, RegisteredAgent] = {}


# ============ API Endpoints ============

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web UI."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.exists():
        return template_path.read_text()
    # Fallback to JSON if no template
    return HTMLResponse(content="<h1>A2A Agent Registry</h1><p>See <a href='/docs'>/docs</a> for API.</p>")


@app.get("/api")
async def api_info():
    """API information endpoint."""
    return {
        "name": "A2A Agent Registry",
        "version": "0.1.0",
        "description": "A public directory for discovering A2A-compatible agents",
        "endpoints": {
            "register": "POST /agents",
            "list": "GET /agents",
            "get": "GET /agents/{agent_id}",
            "search": "GET /agents/search",
        }
    }


@app.post("/agents", response_model=RegisterResponse)
async def register_agent(request: RegisterRequest):
    """Register a new agent in the registry."""
    
    # Generate unique ID based on agent name (slugified)
    base_id = request.card.name.lower().replace(" ", "-").replace("_", "-")
    agent_id = base_id
    
    # Handle collisions
    counter = 1
    while agent_id in agents_db:
        agent_id = f"{base_id}-{counter}"
        counter += 1
    
    # Store the agent
    agents_db[agent_id] = RegisteredAgent(
        id=agent_id,
        card=request.card,
        registered_at=datetime.utcnow(),
        verified=False,
    )
    
    return RegisterResponse(
        success=True,
        agent_id=agent_id,
        message=f"Agent '{request.card.name}' registered successfully",
    )


@app.get("/agents")
async def list_agents(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List all registered agents."""
    all_agents = list(agents_db.values())
    return {
        "agents": all_agents[offset:offset + limit],
        "total": len(all_agents),
        "limit": limit,
        "offset": offset,
    }


@app.get("/agents/search")
async def search_agents(
    skill: Optional[str] = Query(default=None, description="Search by skill ID or name"),
    tag: Optional[str] = Query(default=None, description="Search by tag"),
    q: Optional[str] = Query(default=None, description="Full-text search in name/description"),
    capability: Optional[str] = Query(default=None, description="Filter by capability (streaming, pushNotifications)"),
):
    """Search for agents by various criteria."""
    results = []
    
    for agent in agents_db.values():
        card = agent.card
        
        # Skill filter
        if skill:
            skill_match = any(
                skill.lower() in s.id.lower() or skill.lower() in s.name.lower()
                for s in card.skills
            )
            if not skill_match:
                continue
        
        # Tag filter
        if tag:
            tag_match = any(
                tag.lower() in t.lower()
                for s in card.skills
                for t in s.tags
            )
            if not tag_match:
                continue
        
        # Full-text search
        if q:
            q_lower = q.lower()
            text_match = (
                q_lower in card.name.lower() or
                q_lower in card.description.lower() or
                any(q_lower in s.name.lower() or q_lower in s.description.lower() 
                    for s in card.skills if s.description)
            )
            if not text_match:
                continue
        
        # Capability filter
        if capability and card.capabilities:
            cap_value = getattr(card.capabilities, capability, None)
            if not cap_value:
                continue
        
        results.append(agent)
    
    return {
        "results": results,
        "count": len(results),
        "filters": {
            "skill": skill,
            "tag": tag,
            "q": q,
            "capability": capability,
        }
    }


@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get a specific agent by ID."""
    if agent_id not in agents_db:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agents_db[agent_id]


@app.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Remove an agent from the registry."""
    if agent_id not in agents_db:
        raise HTTPException(status_code=404, detail="Agent not found")
    del agents_db[agent_id]
    return {"success": True, "message": f"Agent {agent_id} removed"}


@app.post("/validate")
async def validate_card(request: RegisterRequest):
    """Validate an Agent Card without registering it."""
    from .validator import validate_agent_card
    result = validate_agent_card(request.card.model_dump())
    return result


# ============ Run ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
