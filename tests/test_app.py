from froggyboot.tools import ReportWatcher
from tests.conftest import basic

TEACHER = "00-1a-2b-3c-4d-5e"
PC = "aa-bb-cc-dd-ee-01"


def auth(client, zone, mac, headers=None, path="windows.ipxe"):
    folder = "secure" if zone == "windows" else "danger"
    h = {"X-Original-URI": f"/{folder}/{path}?mac={mac}", **(headers or {})}
    return client.get(f"/api/auth/{zone}", headers=h)


def test_menu_shows_host_name_and_logs(client):
    r = client.get("/menu.ipxe", params={"mac": PC})
    assert r.status_code == 200 and "set host pc01" in r.text
    assert client.app_db.events(5)[0]["kind"] == "menu"
    assert "set host ${net0/mac:hexhyp}" in client.get("/menu.ipxe").text


def test_auth_password_and_challenge(client):
    r = auth(client, "windows", PC)
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert auth(client, "windows", PC, basic("tech", "wrong")).status_code == 401
    assert auth(client, "windows", PC, basic("tech", "techpass")).status_code == 200
    assert auth(client, "windows", PC, basic("admin", "adminpass")).status_code == 200  # admin can do Windows
    assert auth(client, "danger", PC, basic("tech", "techpass")).status_code == 403   # not whitelisted
    assert auth(client, "danger", TEACHER, basic("tech", "techpass")).status_code == 401
    assert auth(client, "danger", TEACHER, basic("admin", "adminpass")).status_code == 200
    assert client.get("/api/auth/windows").status_code == 403  # no MAC at all


def test_one_time_code_binds_to_first_pc(client):
    r = client.post("/panel/api/codes", json={"zone": "windows", "minutes": 10})
    code = r.json()["code"]
    assert auth(client, "windows", PC, basic("code", code)).status_code == 200
    assert auth(client, "windows", PC, basic("code", code)).status_code == 200
    assert auth(client, "windows", TEACHER, basic("code", code)).status_code == 401
    assert auth(client, "danger", TEACHER, basic("code", code)).status_code == 401  # other zone


def test_ask_approval_flow(client):
    assert auth(client, "windows", PC, basic("ask", "x")).status_code == 401
    pending = client.get("/panel/api/overview").json()["approvals"]
    assert len(pending) == 1 and pending[0]["mac"] == PC
    assert client.post(f"/panel/api/approvals/{pending[0]['id']}", json={"approve": True}).status_code == 200
    assert auth(client, "windows", PC, basic("ask", "x")).status_code == 200
    assert client.post(f"/panel/api/approvals/{pending[0]['id']}", json={"approve": True}).status_code == 409


def test_ask_denied(client):
    auth(client, "windows", PC, basic("ask", "x"))
    aid = client.get("/panel/api/overview").json()["approvals"][0]["id"]
    client.post(f"/panel/api/approvals/{aid}", json={"approve": False})
    assert auth(client, "windows", PC, basic("ask", "x")).status_code == 403


def test_assignment_runs_once(client):
    r = client.post("/panel/api/assign", json={"macs": [PC], "entry": "windows/win_install",
                                               "wim": "install.wim", "index": 6, "disk": 0, "backup": True})
    assert r.status_code == 200, r.text
    menu = client.get("/menu.ipxe", params={"mac": PC}).text
    assert "ADMIN ASSIGNMENT" in menu
    token = menu.split("set password ")[1].split()[0]
    hdr = basic("assign", token)
    assert auth(client, "windows", PC, hdr).status_code == 200
    txt = client.get("/api/froggy.txt", headers={**hdr, "X-Original-URI": f"/secure/froggy.txt?mac={PC}"}).text
    assert "AUTO=1" in txt and "IDX=6" in txt and "HOST=pc01" in txt and "BACKUP=1" in txt and "\r\n" in txt
    # Started: next boot shows the normal menu, so a crash can't loop the install.
    assert "ADMIN ASSIGNMENT" not in client.get("/menu.ipxe", params={"mac": PC}).text
    # The token never works for another PC.
    assert auth(client, "windows", TEACHER, hdr).status_code == 401


def test_froggy_txt_manual_install(client):
    txt = client.get("/api/froggy.txt", headers={**basic("tech", "techpass"),
                                                "X-Original-URI": f"/secure/froggy.txt?mac={TEACHER}"}).text
    assert "AUTO=0" in txt and "HOST=teacher" in txt


def test_assign_validation(client):
    bad = {"macs": [PC], "entry": "windows/win_console", "wim": "install.wim", "index": 1}
    assert client.post("/panel/api/assign", json=bad).status_code == 400
    bad = {"macs": [PC], "entry": "windows/win_install", "wim": "../etc/passwd.wim", "index": 1}
    assert client.post("/panel/api/assign", json=bad).status_code == 400


def test_overview_install_choices_only_install_mode(client):
    ov = client.get("/panel/api/overview").json()
    assert [r for r, _ in ov["install_choices"]] == ["windows/win_install"]
    assert all(not r.startswith(("windows/", "danger/")) for r, _ in ov["exam_choices"])


def test_exam_mode(client):
    assert client.post("/panel/api/exam", json={"entry": "danger/shredos"}).status_code == 400
    assert client.post("/panel/api/exam", json={"entry": "linux/debian"}).status_code == 200
    assert "EXAM MODE" in client.get("/menu.ipxe", params={"mac": PC}).text
    client.post("/panel/api/exam", json={"entry": None})
    assert "EXAM MODE" not in client.get("/menu.ipxe", params={"mac": PC}).text


def test_inventory_and_events(client):
    assert client.post("/api/inventory", params={"mac": PC}, content=b"[1]").status_code == 400
    assert client.post("/api/inventory", params={"mac": PC}, json={"product": "OptiPlex"}).status_code == 200
    assert client.get("/panel/api/inventory", params={"mac": PC}).json()[0]["data"]["product"] == "OptiPlex"
    client.get("/api/event/local", params={"mac": PC})
    host = client.get("/panel/api/overview").json()["rooms"][0]["hosts"][1]
    assert host["status"] == "disk"


def test_report_watcher(tmp_path):
    seen = []
    w = ReportWatcher(tmp_path, lambda *a: seen.append(a))
    f = tmp_path / f"{PC}.log"
    f.write_bytes(b"start|Win 11\r\napply|")
    w.scan()
    assert seen == [(PC, "start", "Win 11")]
    with f.open("ab") as fh:
        fh.write(b"ok\r\ndone|\r\n")
    w.scan()
    assert seen[-2:] == [(PC, "apply", "ok"), (PC, "done", "")]


def test_report_done_finishes_assignment(client, tree):
    client.post("/panel/api/assign", json={"macs": [PC], "entry": "windows/win_install",
                                           "wim": "install.wim", "index": 1})
    client.app.state.watcher.on_step(PC, "done", "")
    a = client.app_db.assignment(PC)
    assert a["status"] == "done"
