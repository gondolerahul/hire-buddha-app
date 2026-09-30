"""SA-14: each hostname has exactly one vhost per port in deploy/apache/.

Certbot appends a `*:80` block to the `-le-ssl.conf` it writes. It did so for
app.hirebuddha.com, with the HTTPS redirect commented out, so two port-80
vhosts answered for the same name and whichever Apache loaded first won.
"""
import re
from collections import Counter
from pathlib import Path

APACHE = Path(__file__).resolve().parents[3] / "deploy" / "apache"

VHOST = re.compile(r"<VirtualHost\s+\*:(\d+)>(.*?)</VirtualHost>", re.S | re.I)
SERVER_NAME = re.compile(r"^\s*ServerName\s+(\S+)", re.M | re.I)


def _vhosts():
    for conf in sorted(APACHE.glob("*.conf")):
        for port, body in VHOST.findall(conf.read_text(encoding="utf-8")):
            name = SERVER_NAME.search(body)
            yield conf.name, port, name.group(1) if name else None, body


def test_one_vhost_per_hostname_and_port():
    counts = Counter((name, port) for _, port, name, _ in _vhosts() if name)
    assert counts, "no vhosts found under deploy/apache"
    assert [key for key, n in counts.items() if n > 1] == []


def test_every_port_80_vhost_redirects_to_https():
    plain = [(conf, name) for conf, port, name, body in _vhosts()
             if port == "80" and not re.search(r"^\s*RewriteRule\s+\^\s+https://", body, re.M)]
    assert plain == []
