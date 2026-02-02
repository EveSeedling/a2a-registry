# A2A Agent Card Schema Notes

From the spec and Python SDK examples.

## AgentCard Fields

```python
AgentCard(
    name='Hello World Agent',           # Required: Display name
    description='Just a hello world',   # Required: What the agent does
    url='http://localhost:9999/',        # Required: Service endpoint
    version='1.0.0',                     # Version string
    default_input_modes=['text'],        # e.g., text, file, audio
    default_output_modes=['text'],       # e.g., text, file, audio  
    capabilities=AgentCapabilities(      # What the agent supports
        streaming=True,
        pushNotifications=False
    ),
    skills=[skill],                      # List of AgentSkill objects
    supports_authenticated_extended_card=True,  # Has extended card for auth'd users
)
```

## AgentSkill Fields

```python
AgentSkill(
    id='hello_world',                    # Unique identifier
    name='Returns hello world',          # Display name
    description='just returns hello',    # What this skill does
    tags=['hello world'],                # Searchable tags
    examples=['hi', 'hello world'],      # Example prompts
)
```

## Discovery Methods (from spec)

1. **Well-Known URI**: `/.well-known/agent-card.json`
2. **Curated Registries**: Central repository with query API (NO STANDARD YET - this is our opportunity!)
3. **Direct Configuration**: Hardcoded/configured endpoints

## Registry API Design (our contribution)

The spec explicitly says: "The current A2A specification does not prescribe a standard API for curated registries."

We can define:
- `POST /agents` - Register agent (submit Agent Card)
- `GET /agents` - List all agents
- `GET /agents/{id}` - Get specific agent
- `GET /agents/search?skill=X&tag=Y` - Search by criteria

## Validation Requirements

- Validate Agent Card against schema
- Optionally verify endpoint is reachable
- Optionally verify `/.well-known/agent-card.json` matches submitted card
