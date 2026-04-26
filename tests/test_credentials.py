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


def test_exits_when_utm_domains_unset(monkeypatch, capsys):
    monkeypatch.delenv("UTM_DOMAINS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_domains_from_env({})

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "UTM_DOMAINS" in captured.err


def test_exits_when_utm_domains_empty_string(monkeypatch, capsys):
    monkeypatch.setenv("UTM_DOMAINS", "")

    with pytest.raises(SystemExit) as exc_info:
        load_domains_from_env()

    assert exc_info.value.code == 2
    assert "UTM_DOMAINS" in capsys.readouterr().err


def test_exits_when_per_domain_vars_missing(monkeypatch, capsys):
    monkeypatch.setenv("UTM_DOMAINS", "dom1")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "monitoring")
    monkeypatch.delenv("UTM_dom1_PASS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        load_domains_from_env()

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "UTM_dom1_PASS" in err
    assert "UTM_dom1_HOST" not in err
    assert "UTM_dom1_USER" not in err


def test_error_message_does_not_leak_existing_values(monkeypatch, capsys):
    secret_value = "super-secret-password-12345"
    monkeypatch.setenv("UTM_DOMAINS", "dom1,dom2")
    monkeypatch.setenv("UTM_dom1_HOST", "10.0.0.10")
    monkeypatch.setenv("UTM_dom1_USER", "monitoring")
    monkeypatch.setenv("UTM_dom1_PASS", secret_value)
    # dom2 missing all vars

    with pytest.raises(SystemExit):
        load_domains_from_env()

    err = capsys.readouterr().err
    assert secret_value not in err
    assert "10.0.0.10" not in err
    assert "monitoring" not in err


def test_whitespace_in_utm_domains_is_tolerated(monkeypatch):
    monkeypatch.setenv("UTM_DOMAINS", "  dom1 , dom2,  dom3  ")
    for domain_id in ("dom1", "dom2", "dom3"):
        monkeypatch.setenv(f"UTM_{domain_id}_HOST", f"10.0.0.{domain_id[-1]}")
        monkeypatch.setenv(f"UTM_{domain_id}_USER", "u")
        monkeypatch.setenv(f"UTM_{domain_id}_PASS", "p")

    domains = load_domains_from_env()

    assert [d.id for d in domains] == ["dom1", "dom2", "dom3"]
