"""Fail-closed authorization parser. Hostnames require exact explicit listing."""
import ipaddress, re
from dataclasses import dataclass

HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*$")

@dataclass
class Scope:
    networks: list
    addresses: set
    hostnames: set

    def allows(self, target: str) -> bool:
        value = target.strip().lower().rstrip('.')
        if value in self.hostnames: return True
        try: ip = ipaddress.ip_address(value)
        except ValueError: return False
        return any(ip in net for net in self.networks) or value in self.addresses

    def describe(self):
        return {"networks": [str(n) for n in self.networks], "addresses": sorted(self.addresses), "hostnames": sorted(self.hostnames)}

def parse_scope(text: str) -> Scope:
    networks, addresses, hostnames = [], set(), set()
    for line_no, raw in enumerate(text.splitlines(), 1):
        item = raw.split('#', 1)[0].strip()
        if not item: continue
        try:
            if '/' in item:
                net = ipaddress.ip_network(item, strict=False)
                if net.version != 4: raise ValueError('IPv4-only starter')
                networks.append(net)
            else:
                try:
                    ip = ipaddress.ip_address(item)
                    if ip.version != 4: raise ValueError('IPv4-only starter')
                    addresses.add(str(ip))
                except ValueError:
                    if not HOST_RE.fullmatch(item): raise ValueError('invalid hostname or address')
                    hostnames.add(item.lower().rstrip('.'))
        except ValueError as exc:
            raise ValueError(f"Invalid scope entry on line {line_no}: {item} ({exc})") from exc
    if not (networks or addresses or hostnames): raise ValueError('Scope file contains no valid targets.')
    return Scope(networks, addresses, hostnames)

def authorize(scope: Scope, target: str):
    if not scope.allows(target):
        raise PermissionError(f"SCOPE DENIED: {target} is not explicitly included in the supplied scope.")
