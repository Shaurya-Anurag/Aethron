import asyncio
import ipaddress
import shutil
import socket
import xml.etree.ElementTree as ET

from .config import settings
from .scope import authorize, Scope


class ScannerError(RuntimeError):
    pass


def _resolve_lab_hostname(target: str) -> str:
    """Resolve an explicitly scoped hostname once and pin Nmap to that validated IP."""
    try:
        answers = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(target, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ScannerError(f"Could not resolve explicitly scoped hostname: {exc}") from exc

    if len(answers) != 1:
        raise ScannerError("Hostname must resolve to exactly one address; ambiguous DNS results are denied.")

    address = next(iter(answers))
    if not (address.is_private or address.is_loopback or address.is_link_local):
        raise ScannerError("Hostname resolution includes a non-private address; live execution denied.")
    return str(address)


async def discover(target: str, scope: Scope):
    # Authorize the exact user-supplied target before any DNS or network operation.
    authorize(scope, target)

    try:
        ipaddress.ip_address(target)
        scan_target = target
    except ValueError:
        # Pin the scanner to the address we validated to avoid a second DNS lookup by Nmap.
        scan_target = _resolve_lab_hostname(target)

    binary = shutil.which(settings.nmap_path)
    if not binary:
        raise ScannerError("Nmap was not found. Install Nmap and ensure it is on PATH.")

    # Fixed arguments only. No user-controlled flags or shell interpolation.
    process = await asyncio.create_subprocess_exec(
        binary,
        "-sT",
        "-sV",
        "--version-light",
        "-Pn",
        "--top-ports",
        "1000",
        "-oX",
        "-",
        scan_target,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=settings.scan_timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise ScannerError("Discovery timed out; no result was accepted.") from exc

    if process.returncode not in (0, 1):
        raise ScannerError(stderr.decode(errors="replace")[-1200:] or "Nmap failed.")

    try:
        root = ET.fromstring(stdout)
    except ET.ParseError as exc:
        raise ScannerError(f"Could not parse Nmap XML: {exc}") from exc

    host = root.find("host")
    if host is None:
        return {"address": target, "state": "unknown", "ports": []}

    status = host.find("status")
    ports = []
    for port in host.findall("./ports/port"):
        state = port.find("state")
        if state is None or state.get("state") != "open":
            continue
        service = port.find("service")
        ports.append(
            {
                "port": int(port.get("portid")),
                "protocol": port.get("protocol", "tcp"),
                "state": state.get("state"),
                "service": service.get("name", "unknown") if service is not None else "unknown",
                "product": service.get("product", "") if service is not None else "",
                "version": service.get("version", "") if service is not None else "",
                "extra": service.get("extrainfo", "") if service is not None else "",
            }
        )

    return {
        "address": target,
        "state": status.get("state", "unknown") if status is not None else "unknown",
        "ports": ports,
    }
