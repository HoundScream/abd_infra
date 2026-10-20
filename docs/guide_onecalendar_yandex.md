# Синхронизация календаря Yandex 360 через OneCalendar (CalDAV)

Рекомендуемое приложение для календаря после миграции с LanCloud: **OneCalendar** (его же указывает поддержка Яндекса).

Работает на **Windows, macOS, iOS, Android**. Календарь синхронизируется с Яндекс 360 по протоколу **CalDAV**.

Почту можно оставить в Outlook / Apple Mail / Яндекс Почте — календарь удобнее вести в OneCalendar.

---

## Общий шаг (для всех устройств): пароль приложения

Обычный пароль от почты **не подойдёт**. Нужен отдельный пароль приложения типа «Календарь».

1. Откройте [Пароли приложений](https://id.yandex.ru/security/app-passwords) (войдите под корпоративным `имя@rubda.ru`).
2. **Создать пароль приложения** → тип **Календарь**.
3. Название, например: `OneCalendar Windows` / `OneCalendar iPhone`.
4. Нажмите **Далее** / **Создать**, **скопируйте пароль** и сохраните.

Пароль показывается **один раз**. Если потеряли — удалите старый и создайте новый.

### Параметры CalDAV (одинаковые везде)

| Поле | Значение |
|------|----------|
| Тип аккаунта | **CalDAV** |
| User name | полный адрес, например `i.ivanov@rubda.ru` |
| Password | **пароль приложения** (не обычный пароль) |
| Server | `https://caldav.yandex.ru` |

Если не подключается:

- User name без домена: только `i.ivanov`
- Advanced / расширенные:
  - SSL: **Да**
  - Port: **443**
  - Account URL: `https://caldav.yandex.ru/principals/users/ВАШ_ЛОГИН@rubda.ru/`

---

## Ссылки на установку

| Платформа | Где скачать |
|-----------|-------------|
| **Android** | [Google Play — One Calendar](https://play.google.com/store/apps/details?id=biz.codespark.xcalendarapp) |
| **iPhone / iPad / Mac** | [App Store — OneCalendar](https://apps.apple.com/app/apple-store/id1238379385) |
| **Windows 10/11** | [Microsoft Store — OneCalendar](https://www.microsoft.com/store/apps/9wzdncrdr0sf) |
| Все ссылки | [onecalendar.nl/download/store](https://www.onecalendar.nl/download/store) |

---

## Windows

1. Установите OneCalendar из Microsoft Store.
2. Создайте пароль приложения «Календарь» (см. выше).
3. В OneCalendar: **Settings** (справа внизу) → **Accounts** → **+**.
4. Тип аккаунта: **CalDAV**.
5. Укажите User name, Password (пароль приложения), Server: `https://caldav.yandex.ru`.
6. При необходимости откройте **Advanced**.
7. **Connect** → отметьте нужные календари → **Done**.

---

## macOS

1. Установите OneCalendar из App Store (одно приложение для Mac и iPhone/iPad).
2. Создайте пароль приложения «Календарь».
3. Меню OneCalendar (слева сверху) → **Accounts** → **+**.
4. Тип: **CalDAV**.
5. User name = `имя@rubda.ru`, Password = пароль приложения, Server = `https://caldav.yandex.ru`.
6. **Connect** → выберите календари → **Done**.

Альтернатива без OneCalendar: системный «Календарь» Apple → добавить CalDAV-аккаунт с теми же параметрами (`caldav.yandex.ru`, путь `/principals/users/имя@rubda.ru/`, порт 443, SSL).

---

## iOS (iPhone / iPad)

1. Установите OneCalendar из App Store.
2. Создайте пароль приложения «Календарь» (удобнее с компьютера, потом вставить в телефон).
3. Откройте OneCalendar → экран **Account type** → **CalDAV**.
4. User name / Password / Server — как в таблице выше.
5. **Connect** → отметьте календари → **Done**.

Если ошибка — User name без `@rubda.ru`, либо Advanced: SSL Да, порт 443, Account URL с полным путём principals.

---

## Android

1. Установите [One Calendar](https://play.google.com/store/apps/details?id=biz.codespark.xcalendarapp) из Google Play.
2. Создайте пароль приложения «Календарь».
3. Меню (☰ слева сверху) → **Accounts** → **+**.
4. Тип: **CalDAV**.
5. User name / Password / Server: `https://caldav.yandex.ru`.
6. При необходимости **Advanced**.
7. **Connect** → выберите календари → **Done**.

---

## Что ожидать после настройки

- События из Яндекс Календаря появляются в OneCalendar на всех устройствах с одним аккаунтом.
- Новые встречи и правки синхронизируются обратно в Яндекс (при интернете).
- Импорт старых `.ics` (если ещё не сделали) — в [calendar.yandex.ru](https://calendar.yandex.ru/) → Импорт; после этого они подтянутся в OneCalendar.

## Если что-то не работает

1. Пароль именно типа **Календарь**, не «Почта».
2. Логин — корпоративный `@rubda.ru`.
3. Server с `https://`.
4. Проверка в браузере: [calendar.yandex.ru](https://calendar.yandex.ru/) — события там есть?
5. Напишите Георгию / в чат миграции — поможем настроить удалённо.

---

*Служебная инструкция по проекту миграции LanCloud → Yandex 360 · Ассоциация больших данных (rubda.ru)*
