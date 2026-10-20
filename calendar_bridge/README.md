# Calendar Bridge — серверное приложение АБД

Автоматические обходы несовместимости **Outlook ↔ Yandex 360**:

| Задача | Что делает |
|--------|------------|
| **incoming_invites** | IMAP → winmail/no_name/TNEF/ICS → событие в Яндекс Календаре |
| **outgoing_invites** | CalDAV → встречи с внешними организациями → досыл .ics |
| **sync_audit** | Проверка IMAP/CalDAV, статистика расхождений |
| **attachment_links** | (заготовка) ссылки на файлы в описании встречи |

## Быстрый старт (Docker)

```bash
cd kalendar_migration/calendar_bridge
cp .env.example .env
# заполнить SECRET_KEY, ADMIN_PASSWORD, SMTP при необходимости
docker compose up -d --build
```

Админка: http://localhost:8091 (порт задаётся в `.env` как `BRIDGE_HTTP_PORT`, по умолчанию 8091).

По умолчанию **DRY_RUN=true** — письма сканируются, события **не создаются**.

## Добавление пользователя

1. В админке → **Пользователи** → email + пароли приложений Яндекс («Почта» и «Календарь»).
2. Задачи запускаются по расписанию или кнопкой «Запустить сейчас».
3. Логи — на странице каждой задачи; обработанные письма — раздел **Письма**.

## Включение записи в календарь

```env
DRY_RUN=false
CREATE_EVENTS_ENABLED=true
```

Для исходящих приглашений дополнительно:

```env
OUTGOING_SEND_ENABLED=true
SMTP_USER=...
SMTP_PASSWORD=...
```

## Дополнительный функционал (план)

- уведомление пользователю «встреча добавлена / не разобрана»;
- загрузка вложений TNEF на Яндекс Диск + ссылка в описании;
- мониторинг free/busy (ограничено API Яндекса);
- webhook в Telegram при ошибках.

## Legacy pilot

Старый одноящиковый режим: `python -m bridge` (SQLite, см. `bridge/pilot.py`).

Документация по кейсам: `../cases.md`, архитектура: `../architecture.md`.
