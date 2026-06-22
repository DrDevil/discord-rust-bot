"""SQLite persistence round-trips and token encryption."""

import pytest

from rustbot.crypto import CryptoError, TokenCipher
from rustbot.persistence.base import ServerStateRecord
from rustbot.persistence.sqlite_store import SqliteRepository

SID = "1.2.3.4:28082"


@pytest.fixture
async def repo(tmp_path):
    store = SqliteRepository(str(tmp_path / "test.db"))
    await store.connect()
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_token_round_trip(repo):
    cipher = TokenCipher(TokenCipher.generate_key())
    encrypted = cipher.encrypt("1234567890")
    assert encrypted != "1234567890"  # stored ciphertext, not plaintext

    await repo.upsert_server(SID, "1.2.3.4", 28082, 76561198000000000, encrypted)
    fetched = await repo.get_encrypted_player_token(SID)
    assert fetched == encrypted
    assert cipher.decrypt(fetched) == "1234567890"


def test_wrong_key_fails_closed():
    cipher = TokenCipher(TokenCipher.generate_key())
    encrypted = cipher.encrypt("secret")
    other = TokenCipher(TokenCipher.generate_key())
    with pytest.raises(CryptoError):
        other.decrypt(encrypted)


@pytest.mark.asyncio
async def test_state_round_trip_survives_restart(tmp_path):
    db = str(tmp_path / "state.db")
    cipher = TokenCipher(TokenCipher.generate_key())

    store = SqliteRepository(db)
    await store.connect()
    await store.upsert_server(SID, "1.2.3.4", 28082, 1, cipher.encrypt("9"))
    await store.save_server_state(
        ServerStateRecord(
            server_id=SID,
            online=True,
            wipe_time=1_700_000_000,
            members={1: True, 2: False},
            member_names={1: "Alice", 2: "Bob"},
        )
    )
    await store.close()

    # Reopen (simulating a restart) and confirm state persisted.
    store2 = SqliteRepository(db)
    await store2.connect()
    record = await store2.load_server_state(SID)
    await store2.close()

    assert record is not None
    assert record.online is True
    assert record.wipe_time == 1_700_000_000
    assert record.members == {1: True, 2: False}
    assert record.member_names == {1: "Alice", 2: "Bob"}


@pytest.mark.asyncio
async def test_load_unknown_server_returns_none(repo):
    assert await repo.load_server_state("nope:0") is None
