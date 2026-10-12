import hashlib
from uuid import UUID, uuid4

import pytest

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.profiles.router import ranking_consent_epoch_header
from calorie_app.modules.profiles.schemas import ConsentInput
from calorie_app.modules.profiles.service import consent_request_hash


@pytest.mark.parametrize("ranking", [False, True])
@pytest.mark.parametrize("energy", [False, True])
@pytest.mark.parametrize("revision", [1, 2147483647])
def test_header_absent_exact_historical_fingerprint(ranking, energy, revision):
    data = ConsentInput(ranking=ranking, automatic_energy_adjustment=energy)
    expected = hashlib.sha256(
        canonical_json(
            {
                "body": {"ranking": ranking, "automatic_energy_adjustment": energy},
                "if_match": revision,
            }
        )
    ).hexdigest()
    assert consent_request_hash(data, revision) == expected
    assert consent_request_hash(data, revision, None) == expected


def test_header_presence_and_epoch_change_are_distinct_semantics():
    data = ConsentInput(ranking=True, automatic_energy_adjustment=False)
    a, b = UUID(int=1), UUID(int=2)
    assert (
        len(
            {
                consent_request_hash(data, 1),
                consent_request_hash(data, 1, a),
                consent_request_hash(data, 1, b),
            }
        )
        == 3
    )


@pytest.mark.parametrize(
    "bad",
    ["", "garbage", " " + str(uuid4()), "{" + str(uuid4()) + "}", str(uuid4()).upper(), "none"],
)
def test_epoch_header_canonical_and_non_echoing(bad):
    with pytest.raises(DomainError) as error:
        ranking_consent_epoch_header(bad)
    assert error.value.code == "invalid_request"
    assert error.value.details == []


def test_epoch_header_optional():
    epoch = uuid4()
    assert ranking_consent_epoch_header(None) is None
    assert ranking_consent_epoch_header(str(epoch)) == epoch
