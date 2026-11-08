import pytest
from app.scope import parse_scope, authorize

def test_explicit_ip():
    s=parse_scope('192.168.1.10')
    assert s.allows('192.168.1.10')
    assert not s.allows('192.168.1.11')

def test_cidr():
    s=parse_scope('10.0.0.0/24')
    assert s.allows('10.0.0.22')
    assert not s.allows('10.0.1.22')

def test_hostname_exact():
    s=parse_scope('lab.internal')
    assert s.allows('LAB.INTERNAL')
    assert not s.allows('sub.lab.internal')

def test_denial():
    s=parse_scope('192.168.0.10')
    with pytest.raises(PermissionError): authorize(s,'192.168.0.11')

def test_invalid_scope():
    with pytest.raises(ValueError): parse_scope('not a target!')
