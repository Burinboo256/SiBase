import json

import check_secrets
import pytest


@pytest.mark.parametrize("leaked", [False, True])
def test_secret_audit_uses_supplied_inventory_without_echoing_values(
    tmp_path, monkeypatch, capsys, leaked
):
    private = tmp_path / "private"
    private.mkdir()
    secret = "synthetic-credential-for-audit-test"
    (private / "fixture-developer.json").write_text(json.dumps({"password": secret}))
    (tmp_path / "guide.md").write_text(secret if leaked else "Safe contributor documentation")
    monkeypatch.setattr(check_secrets, "ROOT", tmp_path)
    monkeypatch.setattr(check_secrets, "PRIVATE", private)
    if leaked:
        with pytest.raises(SystemExit):
            check_secrets.main(["guide.md", ""])
    else:
        check_secrets.main(["guide.md", ""])
    output = capsys.readouterr().out
    assert secret not in output
    assert ("FAIL:" if leaked else "PASS:") in output


def test_secret_audit_rejects_empty_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(check_secrets, "PRIVATE", tmp_path)
    with pytest.raises(SystemExit, match="empty Git inventory"):
        check_secrets.main([""])
