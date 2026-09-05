"""admin cookies must stop verifying after a password change or logout."""
import db
import model


def _fresh_admin(username="root"):
    db.init()
    con = db.connect()
    con.execute("DELETE FROM admins WHERE username=?", (username,))
    con.commit()
    con.close()
    con = db.connect()
    con.execute(
        "INSERT INTO admins (id, username, password_hash, created_at, cookie_epoch) "
        "VALUES (?,?,?,?,0)",
        ("id-" + username, username, model.hash_password("initpw12"), model.now_iso()),
    )
    con.commit()
    con.close()
    return username


def test_valid_cookie_verifies():
    who = _fresh_admin("v1")
    token = model.sign_admin(who)
    assert model.verify_admin(token) == who


def test_password_change_invalidates_cookie():
    who = _fresh_admin("v2")
    token = model.sign_admin(who)
    model.change_password(who, "brandnewpw9")
    assert model.verify_admin(token) is None


def test_logout_epoch_bump_invalidates_cookie():
    who = _fresh_admin("v3")
    token = model.sign_admin(who)
    model.bump_cookie_epoch(who)
    assert model.verify_admin(token) is None


def test_tampered_version_rejected():
    who = _fresh_admin("v4")
    good = model.sign_admin(who)
    forged = model.sign(f"{who}|deadbeefdeadbeef")
    assert model.verify_admin(good) == who
    assert model.verify_admin(forged) is None
