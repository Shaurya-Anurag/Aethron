import json, httpx
from .config import settings
from .models import ActionProposal
from .scope import parse_scope, authorize
from .scanner import discover

ACTIONS = {"discover_services"}

async def propose_next(objective: str, observations: list, targets: list) -> ActionProposal:
    """LLM proposes from a deliberately tiny catalogue; local fallback is deterministic."""
    if not (settings.bifrost_base_url and settings.bifrost_model):
        pending = next((t for t in targets if not any(o.get('address') == t for o in observations)), None)
        if pending: return ActionProposal(action='discover_services', target=pending, rationale='Inspect the next explicitly scoped target.')
        return ActionProposal(action='stop', rationale='All explicitly scoped targets have been inspected.')
    system = (
        'You are AETHRON, a security assessment planner operating only in an isolated authorized lab. '
        'Return one JSON object with action, target, rationale. Allowed actions: discover_services, stop. '
        'Never invent targets. Choose only from the supplied target list. Do not propose exploitation, '
        'credential attacks, shell commands, persistence, or out-of-scope movement. Keep rationale concise.'
    )
    payload = {"objective": objective, "authorized_targets": targets, "observations": observations}
    headers = {"Authorization": f"Bearer {settings.bifrost_api_key}"} if settings.bifrost_api_key else {}
    async with httpx.AsyncClient(timeout=35) as client:
        r = await client.post(settings.bifrost_base_url.rstrip('/') + '/chat/completions', headers=headers, json={
            "model": settings.bifrost_model, "temperature": 0,
            "messages": [{"role":"system","content":system},{"role":"user","content":json.dumps(payload)}],
            "response_format": {"type":"json_object"}
        })
        r.raise_for_status()
        content = r.json()['choices'][0]['message']['content']
    raw = json.loads(content)
    proposal = ActionProposal.model_validate(raw)
    if proposal.action not in ACTIONS | {'stop'}: raise ValueError('Planner proposed an unsupported action.')
    if proposal.action != 'stop' and proposal.target not in targets: raise PermissionError('Planner proposed a target outside the authorized target list.')
    return proposal

async def run_assessment(assessment: dict, emit):
    scope = parse_scope(assessment['scope_text'])
    targets = sorted(scope.addresses | scope.hostnames)
    # Network ranges are not blindly expanded; require explicit target inventory for this starter.
    if scope.networks:
        raise ValueError('CIDR scope is accepted for authorization, but live scanning requires explicit target IPs in this starter. Add lab inventory before scanning a range.')
    if len(targets) > 32: raise ValueError('Target count exceeds the configured safety ceiling.')
    observations = []
    await emit('system', 'Assessment initialized', f'{len(targets)} explicit target(s) loaded. Planner: {"Bifrost" if settings.bifrost_base_url and settings.bifrost_model else "local deterministic fallback"}.')
    for _ in range(len(targets) + 2):
        proposal = await propose_next(assessment['objective'], observations, targets)
        await emit('decision', f"Planner: {proposal.action}", proposal.rationale or 'No rationale supplied.')
        if proposal.action == 'stop': break
        authorize(scope, proposal.target)
        result = await discover(proposal.target, scope)
        observations.append(result)
        await emit('tool', f"Discovery complete · {result['address']}", f"State: {result['state']} · Open TCP services: {len(result['ports'])}")
        await assessment['save_host'](result)
    await emit('system', 'Assessment pass complete', f'{len(observations)} target(s) inspected. Review observations and validate findings before reporting.')
    return observations
