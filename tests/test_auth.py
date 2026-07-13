from server import auth


def test_password_roundtrip():
    h = auth.hash_password("hunter2")
    assert auth.verify_password("hunter2", h)
    assert not auth.verify_password("wrong", h)


def test_token_roundtrip(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "s3cret")
    t = auth.issue_token()
    assert auth.verify_token(t)
    assert not auth.verify_token(t + "x")
    assert not auth.verify_token("garbage")


def test_default_tier_is_3(tmp_path):
    from chassis.config import load_config
    import shutil
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    shutil.copy(root / "config" / "config.yaml", tmp_path / "c.yaml")
    cfg = load_config(tmp_path / "c.yaml")
    assert cfg.tier_for("brand_new_scary_tool") == 3
