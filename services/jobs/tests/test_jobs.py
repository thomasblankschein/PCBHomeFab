import io
import json
import time
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import CONTRACTS, contract_operations, normalize, validate
from fakes import Downstream, _form_field, make_zip, problem
from jobs.config import Settings
from jobs.main import create_app
from jobs.services import Services
from jobs.store import FAILED, JobStore
from jobs.worker import process_next

ZIP = make_zip({"board.gbr": "x"})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_files=3,
        max_boards=50,
        rate_limit_per_hour=5,
        workers=0,
    )


@pytest.fixture
def downstream() -> Downstream:
    return Downstream()


@pytest.fixture
def services(settings: Settings, downstream: Downstream) -> Services:
    return Services(settings, downstream.client())


@pytest.fixture
def client(settings: Settings, services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(settings, services)) as test_client:
        yield test_client


def _post(client: TestClient, *uploads: tuple[str, bytes], counts: list[str] | None = None, **fields: str) -> Any:
    files = [("boards", (name, data, "application/zip")) for name, data in uploads]
    data: dict[str, Any] = {"plate": "160x100", "marks": "false", **fields}
    if counts is not None:
        data["counts"] = counts
    return client.post("/v1/jobs", files=files, data=data)


def _problem(response: Any, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    validate("problem", response.json())
    assert response.json()["code"] == code


def test_routes_match_the_contract(client: TestClient) -> None:
    implemented = {
        (method, normalize(route.path))
        for route in client.app.routes  # type: ignore[attr-defined]
        for method in getattr(route, "methods", None) or ()
    }
    assert contract_operations() <= implemented


def test_job_from_upload_to_download(client: TestClient, services: Services, downstream: Downstream) -> None:
    response = _post(
        client, ("base.zip", ZIP), ("node.zip", ZIP), counts=["1", "3"], exposure_s="90", frame_left_mm="2.5"
    )
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "queued"

    first = client.get(f"/v1/jobs/{job['id']}").json()
    validate("job", first)
    assert first["status"] == "queued"
    assert [(b["name"], b["count"], b["width_mm"]) for b in first["params"]["boards"]] == [
        ("base", 1, 10.0),
        ("node", 3, 10.0),
    ]

    assert process_next(JobStore(services.settings), services)
    status = client.get(f"/v1/jobs/{job['id']}").json()
    validate("job", status)
    assert status["status"] == "done" and status["error"] is None
    names = {f["name"] for f in status["files"]}
    assert names == {
        "mask.png",
        "mask_preview.png",
        "exposure.pm3",
        "copper.png",
        "mill/1_drill_0.8mm.nc",
        "mill/2_mill_1.0mm.nc",
        "mill_gcode.zip",
        "mill_preview.svg",
    }

    pm3 = client.get(f"/v1/jobs/{job['id']}/files/exposure.pm3")
    assert pm3.content == b"ANYCUBIC90.0"
    bundle = zipfile.ZipFile(io.BytesIO(client.get(f"/v1/jobs/{job['id']}/files/mill_gcode.zip").content))
    assert sorted(bundle.namelist()) == ["1_drill_0.8mm.nc", "2_mill_1.0mm.nc"]
    archive = client.get(f"/v1/jobs/{job['id']}/archive")
    assert archive.headers["content-type"] == "application/zip"
    assert archive.headers["content-disposition"] == f'attachment; filename="pcbhomefab-{job["id"][:8]}.zip"'
    assert sorted(zipfile.ZipFile(io.BytesIO(archive.content)).namelist()) == [
        "drill-mill/1_drill_0.8mm.nc",
        "drill-mill/2_mill_1.0mm.nc",
        "drill-mill/mill_preview.svg",
        "exposure/exposure.pm3",
        "exposure/mask.png",
        "exposure/mask_preview.png",
    ]
    preview = client.get(f"/v1/jobs/{job['id']}/files/mask_preview.png")
    assert preview.headers["content-type"] == "image/png" and preview.headers["content-disposition"].startswith(
        "inline"
    )
    assert pm3.headers["content-disposition"].startswith("attachment")

    # every downstream call carries a request id, the id of one job is shared by its steps
    ids = [rid for _, path, rid in downstream.calls if path in ("/v1/layouts", "/v1/masks", "/v1/programs")]
    assert all(rid for rid in ids) and len({rid.rsplit("-", 1)[0] for rid in ids if rid}) == 1


def test_options_reach_the_services(client: TestClient, services: Services, downstream: Downstream) -> None:
    seen: dict[str, Any] = {}
    original = downstream.handle

    def spy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/masks":
            seen["exposure"] = request.content
        if request.url.path == "/v1/layouts":
            seen["panel"] = json.loads(request.content)
        return original(request)

    services.client = httpx.Client(transport=httpx.MockTransport(spy))
    job = _post(client, ("node.zip", ZIP), counts=["2"], gap_mm="5", margin_mm="4", holes="center").json()
    process_next(JobStore(services.settings), services)
    assert seen["panel"]["gap_mm"] == 5 and seen["panel"]["margin_mm"] == 4
    assert seen["panel"]["boards"] == [{"id": "node", "width_mm": 10.0, "height_mm": 26.0, "count": 2}]
    assert b'"holes": "center"' in seen["exposure"]
    assert client.get(f"/v1/jobs/{job['id']}").json()["status"] == "done"


def test_only_selected_outputs_are_run(client: TestClient, services: Services, downstream: Downstream) -> None:
    job = _post(client, ("node.zip", ZIP), mill_gcode="false").json()
    process_next(JobStore(services.settings), services)
    names = {f["name"] for f in client.get(f"/v1/jobs/{job['id']}").json()["files"]}
    assert names == {"mask.png", "mask_preview.png", "exposure.pm3", "copper.png"}
    assert not any(path == "/v1/programs" for _, path, _ in downstream.calls)


def test_mill_only_job_gets_the_copper_picture(client: TestClient, services: Services, downstream: Downstream) -> None:
    job = _post(client, ("node.zip", ZIP), exposure="false").json()
    process_next(JobStore(services.settings), services)
    status = client.get(f"/v1/jobs/{job['id']}").json()
    assert status["status"] == "done"
    names = {f["name"] for f in status["files"]}
    assert "copper.png" in names and "exposure.pm3" not in names and "mill_gcode.zip" in names


def test_mill_only_job_does_not_fail_without_the_copper_picture(
    client: TestClient, services: Services, downstream: Downstream
) -> None:
    downstream.override["exposure"] = lambda _r: problem(
        422, "exposure.plate_too_large", "The plate does not fit on the display."
    )
    job = _post(client, ("node.zip", ZIP), exposure="false").json()
    process_next(JobStore(services.settings), services)
    status = client.get(f"/v1/jobs/{job['id']}").json()
    assert status["status"] == "done"
    assert "copper.png" not in {f["name"] for f in status["files"]}


def test_duplicate_file_names_get_distinct_board_ids(client: TestClient) -> None:
    job = _post(client, ("node.zip", ZIP), ("node.zip", ZIP), ("n o de!.zip", ZIP)).json()
    boards = client.get(f"/v1/jobs/{job['id']}").json()["params"]["boards"]
    assert [b["name"] for b in boards] == ["node", "node-2", "n_o_de_"]


def test_upload_refused_when_ingest_refuses(client: TestClient) -> None:
    _problem(_post(client, ("a.zip", b"not a zip")), 422, "ingest.invalid_zip")


def test_upload_fails_when_ingest_is_unreachable(client: TestClient, downstream: Downstream) -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    downstream.override["ingest"] = down
    _problem(_post(client, ("a.zip", ZIP)), 503, "jobs.upstream_unavailable")


def test_service_error_in_the_worker_fails_the_job_with_its_message(
    client: TestClient, services: Services, downstream: Downstream
) -> None:
    downstream.override["panel"] = lambda _r: problem(422, "panel.does_not_fit", "The boards do not fit on the plate.")
    job = _post(client, ("node.zip", ZIP)).json()
    assert process_next(JobStore(services.settings), services)
    status = client.get(f"/v1/jobs/{job['id']}").json()
    assert status["status"] == FAILED and status["error"] == "The boards do not fit on the plate."


@pytest.mark.parametrize(
    "response",
    [
        lambda _r: httpx.Response(500, text="boom"),
        lambda _r: problem(500, "common.internal", "Internal error while creating the files."),
        lambda _r: problem(422, "common.invalid_request", "Invalid request (settings.printer: nope)."),
        lambda _r: httpx.Response(200, content=b"not a zip", headers={"content-type": "application/zip"}),
        lambda _r: httpx.Response(
            200, content=make_zip({"../evil.txt": "x"}), headers={"content-type": "application/zip"}
        ),
    ],
)
def test_other_failures_give_a_generic_message(
    client: TestClient, services: Services, downstream: Downstream, response: Any
) -> None:
    downstream.override["exposure"] = response
    job = _post(client, ("node.zip", ZIP)).json()
    process_next(JobStore(services.settings), services)
    status = client.get(f"/v1/jobs/{job['id']}").json()
    assert status["status"] == FAILED and status["error"] == "Internal error while creating the files."


def test_busy_service_is_retried(
    client: TestClient, services: Services, downstream: Downstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    original = downstream.handle
    state = {"busy": 2}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/layouts" and state["busy"]:
            state["busy"] -= 1
            return problem(503, "common.busy", "busy", {"Retry-After": "1"})
        return original(request)

    services.client = httpx.Client(transport=httpx.MockTransport(flaky))
    job = _post(client, ("node.zip", ZIP)).json()
    process_next(JobStore(services.settings), services)
    assert client.get(f"/v1/jobs/{job['id']}").json()["status"] == "done"


def test_job_timeout_between_steps(client: TestClient, settings: Settings, downstream: Downstream) -> None:
    slow = replace(settings, job_timeout_s=-1)
    job = _post(client, ("node.zip", ZIP)).json()
    assert process_next(JobStore(slow), Services(slow, downstream.client()))
    status = client.get(f"/v1/jobs/{job['id']}").json()
    assert status["status"] == FAILED and "longer" in status["error"]


def test_upload_validation(client: TestClient) -> None:
    _problem(_post(client, ("a.zip", b"x" * (2 * 1024 * 1024))), 413, "jobs.upload_too_large")
    _problem(_post(client, ("a.zip", ZIP), counts=["1", "2"]), 422, "jobs.invalid_upload")
    _problem(_post(client, ("a.zip", ZIP), counts=["0"]), 422, "jobs.invalid_upload")
    _problem(_post(client, ("a.zip", ZIP), counts=["51"]), 422, "jobs.invalid_upload")
    _problem(_post(client, *[(f"{i}.zip", ZIP) for i in range(4)]), 422, "jobs.invalid_upload")
    _problem(_post(client, ("a.zip", ZIP), exposure="false", mill_gcode="false"), 422, "jobs.invalid_upload")
    _problem(_post(client, ("a.zip", ZIP), exposure_s="0"), 422, "common.invalid_request")
    _problem(_post(client, ("a.zip", ZIP), holes="bogus"), 422, "common.invalid_request")
    _problem(_post(client, ("a.zip", ZIP), printer="../x"), 422, "common.invalid_request")
    _problem(client.post("/v1/jobs"), 422, "common.invalid_request")


def test_unknown_jobs_and_files(client: TestClient) -> None:
    _problem(client.get("/v1/jobs/doesnotexist"), 404, "jobs.not_found")
    _problem(client.get("/v1/jobs/" + "a" * 22), 404, "jobs.not_found")
    job = _post(client, ("node.zip", ZIP)).json()
    _problem(client.get(f"/v1/jobs/{job['id']}/files/exposure.pm3"), 404, "jobs.not_found")  # not done yet
    _problem(client.get(f"/v1/jobs/{job['id']}/archive"), 404, "jobs.not_found")


def test_path_traversal_in_file_name_is_refused(client: TestClient, services: Services, settings: Settings) -> None:
    job = _post(client, ("node.zip", ZIP)).json()
    process_next(JobStore(settings), services)
    (settings.data_dir / "secret.txt").write_text("secret")
    for name in ("..%2F..%2Fsecret.txt", "../../secret.txt", "mill/../../../secret.txt"):
        assert client.get(f"/v1/jobs/{job['id']}/files/{name}").status_code == 404


def test_rate_limit(client: TestClient) -> None:
    codes = [_post(client, ("n.zip", ZIP)).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]
    response = _post(client, ("n.zip", ZIP))
    _problem(response, 429, "jobs.rate_limited")
    assert response.headers["retry-after"] == "3600"


def test_queue_limit(settings: Settings, services: Services) -> None:
    small = replace(settings, max_queued=1, rate_limit_per_hour=50)
    with TestClient(create_app(small, services)) as client:
        assert _post(client, ("n.zip", ZIP)).status_code == 201
        _problem(_post(client, ("n.zip", ZIP)), 503, "jobs.queue_full")


def test_profiles_and_tools_come_from_the_services(client: TestClient, downstream: Downstream) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/profiles" and request.url.host == "exposure":
            return httpx.Response(200, json={"printers": {"photon-m3": {"resolution": [4096, 2560]}}})
        if request.url.path == "/v1/profiles":
            return httpx.Response(200, json={"mills": {"3018pro": {"max_spindle_rpm": 20000}}})
        return httpx.Response(200, json={"source": "built-in", "tools": []})

    downstream.override["exposure"] = answer
    downstream.override["mill"] = answer
    data = client.get("/v1/profiles").json()
    assert data["printers"]["photon-m3"]["resolution"] == [4096, 2560]
    assert data["mills"]["3018pro"]["max_spindle_rpm"] == 20000
    assert data["limits"]["max_files"] == 3
    assert client.get("/v1/tools").json()["source"] == "built-in"
    assert client.get("/healthz").json() == {"status": "ok"}


def test_profiles_when_a_service_is_down(client: TestClient, downstream: Downstream) -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    downstream.override["exposure"] = down
    _problem(client.get("/v1/profiles"), 503, "jobs.upstream_unavailable")


def test_store_claims_oldest_first_and_requeues(settings: Settings) -> None:
    store = JobStore(settings)
    store.create("a" * 22, {"k": 1}, "c")
    time.sleep(0.01)
    store.create("b" * 22, {"k": 2}, "c")
    first = store.claim_next()
    assert first is not None and first.id == "a" * 22
    assert store.requeue_stale(-1) == 1  # everything running counts as stale
    again = store.claim_next()
    assert again is not None and again.id == "a" * 22


def test_expired_jobs_are_deleted(settings: Settings) -> None:
    store = JobStore(replace(settings, job_ttl_s=-1))
    store.create("c" * 22, {}, "c")
    folder = store.job_dir("c" * 22)
    folder.mkdir(parents=True)
    (folder / "x.txt").write_text("x")
    assert store.get("c" * 22) is None
    assert store.delete_expired() == 1
    assert not folder.exists()


def test_worker_threads_end_to_end(settings: Settings, services: Services) -> None:
    live = replace(settings, workers=1)
    with TestClient(create_app(live, services)) as client:
        job = _post(client, ("node.zip", ZIP), counts=["2"]).json()
        deadline = time.time() + 30
        status = "queued"
        while time.time() < deadline and status not in ("done", "failed"):
            time.sleep(0.2)
            status = client.get(f"/v1/jobs/{job['id']}").json()["status"]
        assert status == "done"


def test_contract_examples_are_valid() -> None:
    validate("layout", json.loads((CONTRACTS / "examples" / "layout.json").read_text()))


def test_board_info_returns_board_json(client: TestClient) -> None:
    response = client.post("/v1/boards", files={"file": ("my board.zip", ZIP, "application/zip")})
    assert response.status_code == 200
    board = response.json()
    validate("board", board)
    assert board["name"] == "my_board" and (board["width_mm"], board["height_mm"]) == (10.0, 26.0)


def test_board_info_errors(client: TestClient, downstream: Downstream) -> None:
    _problem(client.post("/v1/boards", files={"file": ("a.zip", b"not a zip")}), 422, "ingest.invalid_zip")
    _problem(
        client.post("/v1/boards", files={"file": ("a.zip", b"x" * (2 * 1024 * 1024))}), 413, "jobs.upload_too_large"
    )
    _problem(client.post("/v1/boards"), 422, "common.invalid_request")

    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    downstream.override["ingest"] = down
    _problem(client.post("/v1/boards", files={"file": ("a.zip", ZIP)}), 503, "jobs.upstream_unavailable")


def test_layout_preview_asks_the_panel_service(client: TestClient) -> None:
    request = json.loads((CONTRACTS / "examples" / "preview-layout-request.json").read_text())
    validate("preview-layout-request", request)
    response = client.post("/v1/layouts", json=request)
    assert response.status_code == 200
    layout = response.json()
    validate("layout", layout)
    assert layout["plate"] == {"width_mm": 160.0, "height_mm": 100.0}
    assert len(layout["placements"]) == 16


def test_layout_preview_errors(client: TestClient, downstream: Downstream) -> None:
    board = {"id": "a", "width_mm": 10, "height_mm": 10, "count": 1}
    _problem(client.post("/v1/layouts", json={"plate": "160x100", "boards": []}), 422, "common.invalid_request")
    _problem(
        client.post("/v1/layouts", json={"plate": "160x100", "boards": [board], "gap_mm": 0}),
        422,
        "common.invalid_request",
    )
    _problem(
        client.post("/v1/layouts", json={"plate": "160x100", "boards": [{**board, "count": 60}] * 2}),
        422,
        "jobs.invalid_upload",
    )
    downstream.override["panel"] = lambda _r: problem(422, "panel.does_not_fit", "The boards do not fit on the plate.")
    response = client.post("/v1/layouts", json={"plate": "160x100", "boards": [board]})
    _problem(response, 422, "panel.does_not_fit")


def test_previews_have_their_own_rate_limit(settings: Settings, services: Services) -> None:
    limited = replace(settings, preview_limit_per_hour=3)
    with TestClient(create_app(limited, services)) as client:
        body = {"plate": "160x100", "boards": [{"id": "a", "width_mm": 10, "height_mm": 10, "count": 1}]}
        codes = [client.post("/v1/layouts", json=body).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        assert _post(client, ("n.zip", ZIP)).status_code == 201  # jobs are not affected


def test_plate_sizes_are_listed(client: TestClient) -> None:
    data = client.get("/v1/plates").json()
    assert data["source"] == "built-in"
    assert [(p["id"], p["width_mm"], p["height_mm"]) for p in data["plates"]] == [
        ("160x100", 160.0, 100.0),
        ("75x100", 75.0, 100.0),
        ("100x75", 100.0, 75.0),
    ]


def test_the_chosen_plate_is_used_and_kept_with_the_job(
    client: TestClient, services: Services, downstream: Downstream
) -> None:
    seen: list[dict[str, Any]] = []
    original = downstream.handle

    def spy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/layouts":
            seen.append(json.loads(request.content))
        return original(request)

    services.client = httpx.Client(transport=httpx.MockTransport(spy))
    job = _post(client, ("a.zip", ZIP), plate="75x100").json()
    process_next(JobStore(services.settings), services)
    assert seen[-1]["plate"] == {"width_mm": 75.0, "height_mm": 100.0}
    params = client.get(f"/v1/jobs/{job['id']}").json()["params"]
    assert params["plate"] == {"id": "75x100", "width_mm": 75.0, "height_mm": 100.0}


def test_a_plate_must_be_chosen_from_the_list(client: TestClient) -> None:
    _problem(_post(client, ("a.zip", ZIP), plate=""), 422, "jobs.invalid_plate")
    _problem(_post(client, ("a.zip", ZIP), plate="200x200"), 422, "jobs.invalid_plate")
    board = {"id": "a", "width_mm": 10, "height_mm": 10, "count": 1}
    _problem(client.post("/v1/layouts", json={"plate": "nope", "boards": [board]}), 422, "jobs.invalid_plate")
    _problem(client.post("/v1/layouts", json={"boards": [board]}), 422, "common.invalid_request")


def test_the_layout_preview_uses_the_plate(client: TestClient) -> None:
    board = {"id": "a", "width_mm": 10, "height_mm": 10, "count": 1}
    layout = client.post("/v1/layouts", json={"plate": "100x75", "boards": [board]}).json()
    assert layout["plate"] == {"width_mm": 100.0, "height_mm": 75.0}


def _spy_settings(services: Services, downstream: Downstream) -> dict[str, dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    original = downstream.handle

    def spy(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/v1/masks", "/v1/programs"):
            seen[request.url.host or ""] = _form_field(request, "settings")
        return original(request)

    services.client = httpx.Client(transport=httpx.MockTransport(spy))
    return seen


def test_positioning_marks_reach_exposure_and_mill(
    client: TestClient, services: Services, downstream: Downstream
) -> None:
    seen = _spy_settings(services, downstream)
    job = _post(client, ("a.zip", ZIP), marks="true", mark_labels="false", margin_mm="5", flip="x").json()
    process_next(JobStore(services.settings), services)
    params = client.get(f"/v1/jobs/{job['id']}").json()["params"]
    # the board (10 x 10 mm at 3, 3) ends at x = 13: the origin mark stands 2 mm right of it (the plate is turned in X)
    expected = [{"x_mm": 2.0, "y_mm": 98.0, "voids": "tr-bl"}, {"x_mm": 15.0, "y_mm": 2.0, "voids": "tr-bl"}]
    assert params["marks"]["points"] == expected
    assert params["marks"]["second_mm"] == {"x_mm": 13.0, "y_mm": 96.0}
    assert params["marks"]["plate_origin_mm"] == {"x_mm": -145.0, "y_mm": -2.0}
    assert seen["exposure"]["marks"] == expected and seen["mill"]["marks"] == expected


def test_mark_labels_name_the_gcode_coordinates(client: TestClient) -> None:
    for flip, origin in (("x", 1), ("y", 0), ("none", 0)):
        job = _post(client, ("a.zip", ZIP), marks="true", margin_mm="5", flip=flip).json()
        points = client.get(f"/v1/jobs/{job['id']}").json()["params"]["marks"]["points"]
        assert [p["label"] for p in points] == ["X0 Y0" if i == origin else "X156 Y96" for i in (0, 1)]
        assert {p["label_flip"] for p in points} == {flip}
        assert [p["label_side"] for p in points] == ["right", "left"]
    job = _post(client, ("a.zip", ZIP), marks="true", mark_labels="false", margin_mm="5").json()
    points = client.get(f"/v1/jobs/{job['id']}").json()["params"]["marks"]["points"]
    assert all("label" not in p for p in points)


def test_marks_depend_on_how_the_plate_is_turned(client: TestClient) -> None:
    job = _post(client, ("a.zip", ZIP), marks="true", margin_mm="5", flip="none").json()
    points = client.get(f"/v1/jobs/{job['id']}").json()["params"]["marks"]["points"]
    assert [(p["x_mm"], p["y_mm"], p["voids"]) for p in points] == [(2.0, 2.0, "tl-br"), (158.0, 98.0, "tl-br")]


def test_no_marks_no_settings(client: TestClient, services: Services, downstream: Downstream) -> None:
    seen = _spy_settings(services, downstream)
    job = _post(client, ("a.zip", ZIP)).json()
    process_next(JobStore(services.settings), services)
    assert "marks" not in seen["exposure"] and "marks" not in seen["mill"]
    assert client.get(f"/v1/jobs/{job['id']}").json()["params"]["marks"] is None


def test_marks_need_room(client: TestClient) -> None:
    _problem(_post(client, ("a.zip", ZIP), marks="true", margin_mm="3"), 422, "jobs.invalid_marks")
