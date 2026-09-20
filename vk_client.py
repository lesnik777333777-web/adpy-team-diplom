"""
Обёртка над VK API.

- users.search с обходом лимита в 1000 через vk.execute.
- photos.getAll + ручная сортировка по лайкам.
- users.get — для команды /favorites.
"""
import vk_api
from vk_api.exceptions import ApiError


class VKClient:
    """Клиент для работы с API ВКонтакте через библиотеку vk_api."""

    SEARCH_LIMIT = 1000       # жёсткий лимит VK на users.search
    MAX_PER_REQUEST = 1000    # максимум записей за один вызов внутри execute
    CHUNK = 1000              # сколько берём с одного поддиапазона возраста

    def __init__(self, token: str):
        self.vk_session = vk_api.VkApi(token=token)
        self.vk = self.vk_session.get_api()

    # ------------------------------------------------------------------ #
    #                          КАНДИДАТЫ                                  #
    # ------------------------------------------------------------------ #
    def get_candidates(
            self,
            city_id: int,
            age_from: int,
            age_to: int,
            gender: int,
            offset: int = 0,
            count: int = 10,
    ) -> list:
        """
        Получить список кандидатов.

        Если offset + count <= 1000 — обычный users.search.
        Иначе — обход лимита через vk.execute (возраст режется на поддиапазоны,
        каждый имеет свой счётчик в 1000).
        """
        target_sex = self._resolve_target_sex(gender)

        if offset + count <= self.SEARCH_LIMIT:
            return self._search_simple(
                city_id, age_from, age_to, target_sex, offset, count
            )

        return self._search_deep(
            city_id, age_from, age_to, target_sex, offset, count
        )

    # ------------------------------------------------------------------ #
    #                          ФОТОГРАФИИ                                 #
    # ------------------------------------------------------------------ #
    def get_top_photos(self, user_id: int, count: int = 3) -> list:
        """Топ-N фото пользователя по количеству лайков."""
        photos: list[dict] = []
        offset = 0

        while True:
            try:
                response = self.vk.photos.getAll(
                    owner_id=user_id,
                    offset=offset,
                    count=200,
                    photo_sizes=1,      # обязательно, иначе не будет sizes
                    skip_hidden=1,
                    need_likes=1,
                    sort=1,
                )
            except ApiError as e:
                raise RuntimeError(f"VK API error: {str(e)}") from e

            items = response.get("items", [])
            photos.extend(items)

            total = response.get("count", 0)
            offset += 200
            if offset >= total or not items:
                break

        photos.sort(
            key=lambda p: p.get("likes", {}).get("count", 0),
            reverse=True,
        )

        return [
            {
                "id": photo["id"],
                "owner_id": photo["owner_id"],
                "access_key": photo.get("access_key"),
                "likes": photo.get("likes", {}).get("count", 0),
                "url": self._get_best_photo_url(photo),
            }
            for photo in photos[:count]
        ]

    # ------------------------------------------------------------------ #
    #                          USERS.GET                                  #
    # ------------------------------------------------------------------ #
    def get_users_info(self, user_ids: list[int]) -> list[dict]:
        """Краткая информация о пользователях (для /favorites)."""
        if not user_ids:
            return []
        try:
            return self.vk.users.get(
                user_ids=",".join(map(str, user_ids)),
                fields="domain,city,sex",
            )
        except ApiError as e:
            raise RuntimeError(f"VK API error: {str(e)}") from e

    # ------------------------------------------------------------------ #
    #                          ВНУТРЕННИЕ                                 #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_target_sex(gender: int) -> int:
        """1 → 2, 2 → 1, иначе 0 (любой пол, параметр sex не передаём)."""
        if gender == 1:
            return 2
        if gender == 2:
            return 1
        return 0

    @staticmethod
    def _base_params(
            city_id: int,
            age_from: int,
            age_to: int,
            target_sex: int,
            offset: int,
            count: int,
    ) -> dict:
        params = {
            "city": city_id,
            "age_from": age_from,
            "age_to": age_to,
            "offset": offset,
            "count": count,
            "fields": "bdate,city,sex,photo_max_orig,domain",
            "has_photo": 1,
            "status": 1,
        }
        if target_sex != 0:
            params["sex"] = target_sex
        return params

    def _search_simple(
            self,
            city_id: int,
            age_from: int,
            age_to: int,
            target_sex: int,
            offset: int,
            count: int,
    ) -> list:
        params = self._base_params(
            city_id, age_from, age_to, target_sex, offset, count
        )
        try:
            return self.vk.users.search(**params).get("items", [])
        except ApiError as e:
            raise RuntimeError(f"VK API error: {str(e)}") from e

    @staticmethod
    def _split_age_ranges(age_from: int, age_to: int, step: int = 1) -> list:
        """Разбить возрастной диапазон на поддиапазоны шириной step лет."""
        if age_to < age_from:
            age_from, age_to = age_to, age_from

        ranges = []
        current = age_from
        while current <= age_to:
            end = min(current + step - 1, age_to)
            ranges.append((current, end))
            current = end + 1
        return ranges

    @staticmethod
    def _build_execute_code(
            city_id: int,
            age_from: int,
            age_to: int,
            target_sex: int,
            offset: int,
            count: int,
            fields: str,
    ) -> str:
        sex_line = f'"sex": {target_sex},' if target_sex != 0 else ""
        return f"""
        var r = API.users.search({{
            "city": {city_id},
            "age_from": {age_from},
            "age_to": {age_to},
            {sex_line}
            "offset": {offset},
            "count": {count},
            "fields": "{fields}",
            "has_photo": 1,
            "status": 1
        }});
        return r.items;
        """

    def _search_deep(
            self,
            city_id: int,
            age_from: int,
            age_to: int,
            target_sex: int,
            offset: int,
            count: int,
    ) -> list:
        """Обход лимита в 1000 через vk.execute + разбиение по возрасту."""
        fields = "bdate,city,sex,photo_max_orig,domain"
        ranges = self._split_age_ranges(age_from, age_to, step=1)

        collected: list[dict] = []
        need = offset + count

        for (a_from, a_to) in ranges:
            local_count = min(self.CHUNK, need - len(collected))
            if local_count <= 0:
                break

            code = self._build_execute_code(
                city_id=city_id,
                age_from=a_from,
                age_to=a_to,
                target_sex=target_sex,
                offset=0,
                count=local_count,
                fields=fields,
            )

            try:
                chunk = self.vk_session.method("execute", {"code": code})
            except ApiError as e:
                raise RuntimeError(f"VK API error: {str(e)}") from e

            if isinstance(chunk, list):
                collected.extend(chunk)

        return collected[offset: offset + count]

    @staticmethod
    def _get_best_photo_url(photo: dict) -> str | None:
        """Лучший URL из photo['sizes'] (w > z > y > x > r > q > m > s)."""
        sizes = photo.get("sizes") or []
        if not sizes:
            return None

        priority = ["w", "z", "y", "x", "r", "q", "m", "s"]
        sizes_sorted = sorted(
            sizes,
            key=lambda s: priority.index(s["type"])
            if s["type"] in priority
            else len(priority),
        )
        return sizes_sorted[0].get("url")