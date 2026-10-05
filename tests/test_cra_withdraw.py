"""CR-A: iedzīvotājs atsauc iesniegumu (POST /submissions/{id}/withdraw)."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import clock, storage
from app.main import app

REASON = "Problēma jau ir atrisināta"


def create(client, payload, status="RECEIVED"):
    submission_id = client.post("/submissions", json=payload).json()["id"]
    if status != "RECEIVED":
        assert storage.change_status(submission_id, status, ("RECEIVED",))
    return submission_id


def status_of(client, submission_id):
    return client.get(f"/submissions/{submission_id}").json()["status"]


def actions_of(client, submission_id):
    audit = client.get(f"/submissions/{submission_id}/audit").json()
    return [entry["action"] for entry in audit]


@pytest.mark.parametrize("status", ["RECEIVED", "IN_PROGRESS"])
def test_withdraw_allowed_status(client, valid_payload, status):
    # 1. un 2. kritērijs
    submission_id = create(client, valid_payload, status)

    response = client.post(
        f"/submissions/{submission_id}/withdraw", json={"reason": REASON}
    )

    assert response.status_code == 200
    assert response.json()["id"] == submission_id
    assert response.json()["status"] == "WITHDRAWN"
    assert status_of(client, submission_id) == "WITHDRAWN"


def test_withdraw_keeps_due_date(client, valid_payload):
    # Precizējums: dueDate nemainās
    submission_id = create(client, valid_payload)
    due_date = client.get(f"/submissions/{submission_id}").json()["dueDate"]

    response = client.post(
        f"/submissions/{submission_id}/withdraw", json={"reason": REASON}
    )

    assert response.json()["dueDate"] == due_date


@pytest.mark.parametrize("status", ["ANSWERED", "WITHDRAWN", "FORWARDED"])
def test_withdraw_not_allowed_status(client, valid_payload, status):
    # 3. un 4. kritērijs. FORWARDED: lēmums, kamēr pieteikumā jautājums atvērts.
    submission_id = create(client, valid_payload, status)

    response = client.post(
        f"/submissions/{submission_id}/withdraw", json={"reason": REASON}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    assert status_of(client, submission_id) == status
    assert "WITHDRAW" not in actions_of(client, submission_id)


def test_withdraw_twice_returns_409(client, valid_payload):
    # 4. kritērijs: atkārtota atsaukšana
    submission_id = create(client, valid_payload)
    url = f"/submissions/{submission_id}/withdraw"
    assert client.post(url, json={"reason": REASON}).status_code == 200

    response = client.post(url, json={"reason": REASON})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    assert actions_of(client, submission_id).count("WITHDRAW") == 1


def test_withdraw_unknown_id_returns_404(client):
    # 5. kritērijs
    response = client.post(
        "/submissions/IES-2026-999999/withdraw", json={"reason": REASON}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": None},
        {"reason": ""},
        {"reason": "x" * 9},
        {"reason": "x" * 501},
    ],
    ids=["missing", "null", "empty", "9-chars", "501-chars"],
)
def test_withdraw_invalid_reason(client, valid_payload, body):
    # 6. kritērijs
    submission_id = create(client, valid_payload)

    response = client.post(f"/submissions/{submission_id}/withdraw", json=body)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [d["field"] for d in error["details"]] == ["reason"]
    assert status_of(client, submission_id) == "RECEIVED"
    assert "WITHDRAW" not in actions_of(client, submission_id)


@pytest.mark.parametrize("length", [10, 500])
def test_withdraw_reason_length_boundaries(client, valid_payload, length):
    # 6. kritērijs: robežvērtības ir atļautas
    submission_id = create(client, valid_payload)

    response = client.post(
        f"/submissions/{submission_id}/withdraw", json={"reason": "x" * length}
    )

    assert response.status_code == 200


def test_withdraw_reason_spaces_count_as_contract_says(client, valid_payload):
    # Līgumā ir tikai minLength/maxLength: atstarpes skaitās, tekstu neapgriež.
    reason = "   abcdefghi   "
    submission_id = create(client, valid_payload)

    response = client.post(
        f"/submissions/{submission_id}/withdraw", json={"reason": reason}
    )

    assert response.status_code == 200
    audit = client.get(f"/submissions/{submission_id}/audit").json()
    assert audit[-1]["detail"] == reason


def test_withdraw_writes_audit_entry(client, valid_payload):
    # 7. kritērijs
    submission_id = create(client, valid_payload)
    client.post(f"/submissions/{submission_id}/withdraw", json={"reason": REASON})

    audit = client.get(f"/submissions/{submission_id}/audit").json()

    assert [e["action"] for e in audit] == ["CREATE", "WITHDRAW"]
    assert audit[-1]["detail"] == REASON


def test_withdraw_audit_failure_keeps_status(client, valid_payload, monkeypatch):
    # 7. kritērijs: atsaukšana bez audita ieraksta nedrīkst palikt
    submission_id = create(client, valid_payload)

    def broken_clock():
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(clock, "now", broken_clock)
    unsafe_client = TestClient(app, raise_server_exceptions=False)

    response = unsafe_client.post(
        f"/submissions/{submission_id}/withdraw", json={"reason": REASON}
    )

    assert response.status_code == 500
    monkeypatch.undo()
    assert status_of(client, submission_id) == "RECEIVED"
    assert actions_of(client, submission_id) == ["CREATE"]


def test_withdraw_no_personal_data_in_logs_or_errors(client, valid_payload, caplog):
    # 8. kritērijs
    secrets = [valid_payload[k] for k in ("personalCode", "fullName", "email")]
    secrets.append(valid_payload["body"])
    submission_id = create(client, valid_payload)
    url = f"/submissions/{submission_id}/withdraw"
    caplog.clear()

    with caplog.at_level(logging.DEBUG):
        responses = [
            client.post(url, json={"reason": "short"}),
            client.post(url, json={"reason": REASON}),
            client.post(url, json={"reason": REASON}),
            client.post("/submissions/IES-2026-999999/withdraw", json={}),
            client.post(
                "/submissions/IES-2026-999999/withdraw", json={"reason": REASON}
            ),
        ]

    assert [r.status_code for r in responses] == [400, 200, 409, 400, 404]
    error_texts = [r.text for r in responses if r.status_code >= 400]
    for secret in secrets:
        assert secret not in caplog.text
        for text in error_texts:
            assert secret not in text
