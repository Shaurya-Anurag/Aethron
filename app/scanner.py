import asyncio, json, shutil, socket, ipaddress, xml.etree.ElementTree as ET
from .config import settings
from .scope import authorize, Scope

class ScannerError(RuntimeError): pass

async def discover(target: str, scope: Scope):
    authorize(scope, target)
    # A hostname is permitted only when it resolves exclusively to private/loopback/link-local lab addresses.
    try:
        ipaddress.ip_address(target)
    except ValueError:
        try:
            resolved = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(target, None, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ScannerError(f'Could not resolve explicitly scoped hostname: {exc}')
        if not resolved or any(not (ip.is_private or ip.is_loopback or ip.is_link_local) for ip in resolved):
            raise ScannerError('Hostname resolution includes a non-private address; live execution denied.')
    binary = shutil.which(settings.nmap_path)
    if not binary: raise ScannerError('Nmap was not found. Install Nmap and ensure it is on PATH.')
    # Fixed arguments only. No user-controlled flags or shell interpolation.
    proc = await asyncio.create_subprocess_exec(
        binary, '-sT', '-sV', '--version-light', '-Pn', '--top-ports', '1000',
        '-oX', '-', target,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.scan_timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill(); await proc.communicate(); raise ScannerError('Discovery timed out; no result was accepted.')
    if proc.returncode not in (0, 1):
        raise ScannerError(stderr.decode(errors='replace')[-1200:] or 'Nmap failed.')
    try: root = ET.fromstring(stdout)
    except ET.ParseError as exc: raise ScannerError(f'Could not parse Nmap XML: {exc}')
    host = root.find('host')
    if host is None: return {"address": target, "state": "unknown", "ports": []}
    status = host.find('status')
    ports = []
    for p in host.findall('./ports/port'):
        state = p.find('state')
        if state is None or state.get('state') != 'open': continue
        svc = p.find('service')
        ports.append({
            "port": int(p.get('portid')), "protocol": p.get('protocol', 'tcp'),
            "state": state.get('state'), "service": svc.get('name', 'unknown') if svc is not None else 'unknown',
            "product": svc.get('product', '') if svc is not None else '',
            "version": svc.get('version', '') if svc is not None else '',
            "extra": svc.get('extrainfo', '') if svc is not None else ''
        })
    return {"address": target, "state": status.get('state', 'unknown') if status is not None else 'unknown', "ports": ports}
