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
