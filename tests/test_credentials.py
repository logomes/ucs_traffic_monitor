import pytest

from credentials import Domain, load_domains_from_env


def test_loads_single_domain_with_all_vars(monkeypatch):
    monkeypatch.setenv("UTM_DOMAINS", "dom1")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "monitoring")
    monkeypatch.setenv("UTM_dom1_PASS", "s3cret")
    monkeypatch.setenv("UTM_dom1_GROUP", "production")

    domains = load_domains_from_env()

    assert domains == [
        Domain(
            id="dom1",
            host="10.0.0.10",
            user="monitoring",
            password="s3cret",
            group="production",
        )
    ]
