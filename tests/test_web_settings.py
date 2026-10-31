from yolk.db.connection import connect
from yolk.foods import create_item
from yolk.macros import Macros


def _add_beans(path):
    conn = connect(path)
    create_item(
        conn, name="Black beans", role="carb",
        macros=Macros(kcal=132, carb_g=23.7, fiber_g=8.7, protein_g=8.9),
        units={"cup": 172.0},
    )
    conn.close()


def test_settings_shows_point_sizes(client):
    text = client.get("/settings").text
    assert "15 g" in text and "25 g" in text and "10 g" in text
    assert 'value="total" checked' in text


def test_header_links_to_settings(client):
    assert 'href="/settings"' in client.get("/plans").text


def test_switching_to_net_changes_points(client, seeded):
    _add_beans(seeded[0])
    before = client.get("/foods", params={"q": "black beans"}).text
    # Total: one carb point is 105 g, so ½ cup (86 g) is about ¾C.
    assert "½ cup (86 g) → ¾C" in before

    response = client.post("/settings/carb-basis", data={"basis": "net"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"

    after = client.get("/foods", params={"q": "black beans"}).text
    # Net of 8.7 g fiber: one carb point is 167 g, about 1 cup.
    assert "1 cup (172 g) → 1C" in after
    assert 'value="net" checked' in client.get("/settings").text


def test_bad_basis_is_rejected(client):
    response = client.post("/settings/carb-basis", data={"basis": "gross"})
    assert response.status_code == 422
    assert "total" in response.text and "net" in response.text


def test_cross_site_post_refused(client):
    response = client.post(
        "/settings/carb-basis", data={"basis": "net"},
        headers={"origin": "https://example.com"},
    )
    assert response.status_code == 403
