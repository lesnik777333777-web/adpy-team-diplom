"""Тесты CRUD-слоя."""
import pytest

from database import (
    add_to_blacklist,
    add_user,
    add_viewed_profile,
    count_viewed_profiles,
    get_blacklisted_ids,
    get_favorite_candidate_ids,
    get_user,
    remove_from_blacklist,
    set_favorited,
)


def test_add_user_creates(db):
    user = add_user(db, vk_id=111, city="1", age_from=20, age_to=25, gender=2)
    assert user.id is not None
    assert user.vk_id == 111
    assert user.city == "1"
    assert user.age_from == 20
    assert user.gender == 2

    fetched = get_user(db, 111)
    assert fetched is not None
    assert fetched.id == user.id


def test_add_user_updates_existing(db):
    first = add_user(db, vk_id=222, city="1", age_from=20, age_to=30, gender=1)
    second = add_user(db, vk_id=222, city="2", age_from=25, age_to=35, gender=2)

    assert first.id == second.id
    assert second.city == "2"
    assert second.age_from == 25
    assert second.gender == 2
    assert count_viewed_profiles(db, 222) == 0


def test_add_viewed_profile_creates_and_no_duplicates(db):
    add_user(db, vk_id=333)
    v1 = add_viewed_profile(db, 333, candidate_vk_id=9001)
    v2 = add_viewed_profile(db, 333, candidate_vk_id=9001)

    assert v1.id == v2.id
    assert count_viewed_profiles(db, 333) == 1


def test_viewed_profile_none_does_not_reset_favorite(db):
    add_user(db, vk_id=444)
    add_viewed_profile(db, 444, candidate_vk_id=100, is_favorited=True)
    add_viewed_profile(db, 444, candidate_vk_id=100, is_favorited=None)

    assert get_favorite_candidate_ids(db, 444) == [100]


def test_add_viewed_profile_raises_if_user_missing(db):
    with pytest.raises(ValueError):
        add_viewed_profile(db, 9999, candidate_vk_id=1)


def test_set_favorited_marks_existing(db):
    add_user(db, vk_id=555)
    add_viewed_profile(db, 555, candidate_vk_id=700)
    set_favorited(db, 555, 700)
    assert get_favorite_candidate_ids(db, 555) == [700]


def test_count_viewed_profiles(db):
    add_user(db, vk_id=666)
    assert count_viewed_profiles(db, 666) == 0

    for i in range(5):
        add_viewed_profile(db, 666, candidate_vk_id=1000 + i)
    assert count_viewed_profiles(db, 666) == 5


def test_add_to_blacklist_idempotent(db):
    add_user(db, vk_id=777)
    b1 = add_to_blacklist(db, 777, candidate_vk_id=42)
    b2 = add_to_blacklist(db, 777, candidate_vk_id=42)

    assert b1.id == b2.id
    assert get_blacklisted_ids(db, 777) == [42]


def test_get_blacklisted_ids_order(db):
    add_user(db, vk_id=888)
    add_to_blacklist(db, 888, candidate_vk_id=1)
    add_to_blacklist(db, 888, candidate_vk_id=2)
    add_to_blacklist(db, 888, candidate_vk_id=3)

    # Свежие сверху.
    assert get_blacklisted_ids(db, 888) == [3, 2, 1]


def test_remove_from_blacklist(db):
    add_user(db, vk_id=999)
    add_to_blacklist(db, 999, candidate_vk_id=10)

    assert remove_from_blacklist(db, 999, 10) is True
    assert remove_from_blacklist(db, 999, 10) is False
    assert get_blacklisted_ids(db, 999) == []


def test_blacklist_isolated_between_users(db):
    add_user(db, vk_id=1001)
    add_user(db, vk_id=1002)
    add_to_blacklist(db, 1001, candidate_vk_id=55)
    assert get_blacklisted_ids(db, 1002) == []