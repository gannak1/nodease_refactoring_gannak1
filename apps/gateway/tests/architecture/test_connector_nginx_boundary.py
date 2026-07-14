from pathlib import Path


def test_nginx_connector_test_location_has_bounded_secret_ingress() -> None:
    config = (
        Path(__file__).parents[4] / "docker" / "nginx" / "nginx.conf"
    ).read_text(encoding="utf-8")
    marker = "location = /api/v1/connectors/test"
    start = config.index(marker)
    end = config.index("location /api", start)
    block = config[start:end]

    assert "access_log off;" in block
    assert "error_log /dev/null;" in block
    assert "client_max_body_size 32k;" in block
    assert "client_body_timeout 5s;" in block
    assert "proxy_request_buffering off;" in block
