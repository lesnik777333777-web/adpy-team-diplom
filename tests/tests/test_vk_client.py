"""Тесты VKClient — с замоканным VK API."""
from unittest.mock import MagicMock

import pytest

from vk_client import VKClient


@pytest.fixture
def client(mocker):
    """VKClient с полностью замоканным внутренним API."""
    c = VKClient.__new__(VKClient)  # не вызываем __init__ (он бы дёрнул vk_api)
    c.vk_session = MagicMock()
    c.vk = MagicMock()
    return c


# --------------------------- чистые методы ------------------------------- #

@pytest.mark.parametrize(
    "gender, expected",
    [(1, 2), (2, 1), (0, 0), (99, 0)],
)
def test_resolve_target_sex(gender, expected):
    assert VKClient._resolve_target_sex(gender) == expected


def test_split_age_ranges():
    assert VKClient._split_age_ranges(18, 20) == [(18, 18), (19, 19), (20, 20)]
    assert VKClient._split_age_ranges(20, 18) == [(18, 18), (19, 19), (20, 20)]


def test_get_best_photo_url_prefers_w():
    photo = {
        "sizes": [
            {"type": "m", "url": "u_m"},
            {"type": "w", "url": "u_w"},
            {"type": "x", "url": "u_x"},
        ]
    }
    assert VKClient._get_best_photo_url(photo) == "u_w"


def test_get_best_photo_url_empty_sizes():
    assert VKClient._get_best_photo_url({"sizes": []}) is None
    assert VKClient._get_best_photo_url({}) is None


# ------------------------------ поиск ------------------------------------ #

def test_get_candidates_simple_uses_users_search(client):
    client.vk.users.search.return_value = {"items": [{"id": 1}, {"id": 2}]}

    result = client.get_candidates(
        city_id=1, age_from=18, age_to=30, gender=1, offset=0, count=10
    )

    assert [c["id"] for c in result] == [1, 2]
    client.vk.users.search.assert_called_once()
    kwargs = client.vk.users.search.call_args.kwargs
    assert kwargs["sex"] == 2
    assert kwargs["city"] == 1
    assert kwargs["age_from"] == 18


def test_get_candidates_gender_zero_no_sex_param(client):
    client.vk.users.search.return_value = {"items": []}
    client.get_candidates(city_id=1, age_from=18, age_to=30, gender=0)
    kwargs = client.vk.users.search.call_args.kwargs
    assert "sex" not in kwargs


def test_get_candidates_deep_uses_execute(client):
    """offset + count > 1000 → должен пойти vk.execute, а не users.search."""
    client.vk_session.method.return_value = [{"id": i} for i in range(1, 11)]

    result = client.get_candidates(
        city_id=1, age_from=18, age_to=20, gender=1, offset=1500, count=10
    )

    client.vk.users.search.assert_not_called()
    client.vk_session.method.assert_called()
    assert all("id" in c for c in result)
    args, kwargs = client.vk_session.method.call_args
    assert args[0] == "execute"
    assert "code" in kwargs


def test_get_candidates_propagates_api_error(client):
    from vk_api.exceptions import ApiError

    fake_error = ApiError(MagicMock(), "boom")
    fake_error.code = 5
    fake_error.error_msg = "auth failed"
    client.vk.users.search.side_effect = fake_error

    with pytest.raises(RuntimeError, match="auth failed"):
        client.get_candidates(city_id=1, age_from=18, age_to=30, gender=1)


# ------------------------------ фото ------------------------------------- #

def test_get_top_photos_sorted_by_likes(client):
    def _photo(pid, likes):
        return {
            "id": pid,
            "owner_id": -1,
            "likes": {"count": likes},
            "sizes": [{"type": "w", "url": f"u_{pid}"}],
        }

    client.vk.photos.getAll.return_value = {
        "count": 3,
        "items": [_photo(1, 5), _photo(2, 100), _photo(3, 20)],
    }

    result = client.get_top_photos(user_id=1, count=3)

    assert [p["id"] for p in result] == [2, 3, 1]
    assert result[0]["likes"] == 100
    assert result[0]["url"] == "u_2"


def test_get_top_photos_respects_count(client):
    client.vk.photos.getAll.return_value = {
        "count": 2,
        "items": [
            {"id": 1, "owner_id": -1, "likes": {"count": 1}, "sizes": []},
            {"id": 2, "owner_id": -1, "likes": {"count": 2}, "sizes": []},
        ],
    }
    result = client.get_top_photos(user_id=1, count=1)
    assert len(result) == 1
    assert result[0]["id"] == 2
    assert result[0]["url"] is None