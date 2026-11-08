import pytest

from app.scope import authorize, parse_scope


def test_explicit_ip():
    scope = parse_scope("192.168.1.10")
    assert scope.allows("192.168.1.10")
    assert not scope.allows("192.168.1.11")


def test_cidr():
    scope = parse_scope("10.0.0.0/24")
    assert scope.allows("10.0.0.22")
    assert not scope.allows("10.0.1.22")


def test_hostname_exact():
    scope = parse_scope("lab.internal")
    assert scope.allows("LAB.INTERNAL")
    assert not scope.allows("sub.lab.internal")


def test_denial():
    scope = parse_scope("192.168.0.10")
    with pytest.raises(PermissionError):
        authorize(scope, "192.168.0.11")


def test_invalid_scope():
    with pytest.raises(ValueError):
        parse_scope("not a target!")


def test_empty_scope():
    with pytest.raises(ValueError):
        parse_scope("# only a comment\n\n")


def test_ipv6_is_rejected():
    with pytest.raises(ValueError):
        parse_scope("2001:db8::1")


def test_invalid_cidr_is_rejected():
    with pytest.raises(ValueError):
        parse_scope("192.168.1.1/99")
