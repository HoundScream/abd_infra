# Live-проверка сервисов АБД · 15.10.2026

Проверка с рабочей станции исполнителя (без доступа в консоль YC folder песочницы на момент проверки — см. § «Yandex Cloud API»).

---

## 1. Краткий вердикт

| Контур | Статус снаружи | Комментарий |
|--------|----------------|-------------|
| VPN песочницы (`cpe` / OpenConnect) | **Недоступен** | DNS есть, TCP 22/80/443 на публичный IP — timeout/closed |
| SSO Keycloak (`sso:8443`) | **Недоступен** | DNS есть, порт закрыт |
| Внутренние ВМ idm/armds01/logcltr | **Нет публичных A-записей** | Ожидаемо; доступ только изнутри / через VPN |
| `calc.rubda.ru` | **Недоступен с этой сети** | DNS → `51.250.107.62`, TCP 22/80/443 timeout |
| LanCloud EWS (`mail.lancloud.ru`) | **Хост жив, логин мёртв** | `UnauthorizedError` для `migration_svc@rubda.ru` |
| SharePoint LanCloud DNS | Резолвится | `sprubda.lancloud.ru` → `45.84.84.60` |
| Yandex Calendar / почта 360 | DNS жив | Продуктовый контур, не песочница |

**Вывод по VPN «для зарубежных / пользователей песочницы»:** по публичной сети сервис **сейчас не поднят**. Это согласуется с документацией: контур замораживали; playbooks восстановления 01–08 по отчёту июля **не закрыты**. Чтобы подтвердить статус ВМ (STOPPED vs RUNNING без SG), нужен вход в Yandex Cloud folder `b1ge40a4pthgp0qrb8qr`.

---

## 2. Песочница — DNS и порты

### 2.1. DNS

| Имя | A-запись 15.10.2026 |
|-----|---------------------|
| `cpe.sandbox.rubda.ru` | `158.160.51.221` |
| `sso.sandbox.rubda.ru` | `158.160.127.119` |
| `idm.sandbox.rubda.ru` | — (пусто) |
| `armds01.sandbox.rubda.ru` | — |
| `logcltr.sandbox.rubda.ru` | — |
| `nat.sandbox.rubda.ru` | — |

### 2.2. TCP probe (timeout ~4 с)

| Цель | Порт | Результат |
|------|------|-----------|
| `158.160.51.221` (cpe) | 22 SSH | FAIL |
| `158.160.51.221` | 80 certbot | FAIL |
| `158.160.51.221` | 443 OpenConnect | FAIL |
| `158.160.127.119` (sso/nat) | 22 | FAIL |
| `158.160.127.119` | 443 | FAIL |
| `158.160.127.119` | 8443 Keycloak | FAIL |

### 2.3. Что должно быть по IaC (из `CI/TF/terraform.tfstate`)

Состояние в state-файле (историческое, дата артефактов ~2025; **не путать с live**):

| ВМ | FQDN | Internal IP | NAT IP | Роль |
|----|------|-------------|--------|------|
| cpe | cpe.sandbox.rubda.ru | 10.128.0.5 | **158.160.51.221** | VPN OpenConnect |
| sso | sso.sandbox.rubda.ru | 10.128.0.11 | 158.160.127.119 | Keycloak |
| nat | nat.sandbox.rubda.ru | 10.128.0.3 | 158.160.127.119 | gateway (в inventory отключён) |
| idm | idm.sandbox.rubda.ru | 10.128.0.10 | — | FreeIPA |
| armds01 | armds01.sandbox.rubda.ru | 10.128.0.100 | — | XRDP kiosk |
| logcltr | logcltr.sandbox.rubda.ru | 10.128.0.6 | — | journald collector |

Cloud / folder:

- cloud: `b1g9nbvkf50o4fk6bkd8`
- folder: `b1ge40a4pthgp0qrb8qr`
- subnet: `10.128.0.0/24`, zone `ru-central1-a`
- VPN-клиентские сети в route table: `10.255.255.0/25`, `10.255.255.128/25` → next hop `10.128.0.5` (cpe)

Security group `vpn_server_sg`: с интернета разрешены 22, 80, 443. Если ВМ RUNNING, а порты молчат — ВМ остановлена, сменился IP, или SG/firewall изменены вручную.

---

## 3. VPN — как устроен (не «гостовский»)

Основной автоматизированный VPN в `CI/`:

- **OpenConnect (ocserv)** на `cpe`
- Playbook: `CI/playbooks/99-optional.install-vpn-server.yml` + установка из `01.setup_yc_base_infra.yml`
- Роль: `CI/roles/openconnecthost`
- Auth: PAM → FreeIPA; есть plain secrets для SA (`ocserv_sa_password` в secrets)
- Клиенты: OpenConnect / AnyConnect-совместимые

Дополнительно в коде (не в основной цепочке 01–08):

- роль **StrongSwan** (`strongswanhost`) — IKEv2 для админов / ARMDS (`group_vars/vpnserver/ipsec_connections.yml`)
- в документации упоминается **«гостовский» VPN** — legacy, **только в консоли YC**, не в Terraform

Маршрут пользователя DS: VPN → RDP на `armds01:3389` → Chromium/DataSphere.

Подробности: `docs/docs_pesochinca_from_meeting.md` § 6.2.

---

## 4. Калькулятор `calc.rubda.ru`

| Проверка | Результат |
|----------|-----------|
| DNS | `51.250.107.62` |
| HTTPS / HTTP / SSH с этой сети | timeout |
| Исходники | GitLab `gitlab.com/d-pcc/d-pcc-frontend`, `d-pcc-backend` (в локальном архиве кода нет — только `web-calc/command.sh`) |
| TLS | Let's Encrypt на хосте; копии PEM в `ssl/web-calc/` |
| По плану АБД | сертификат/доступы делались; полный аудит безопасности calc (п. 3.x) — в долге |

---

## 5. LanCloud

| Проверка | Результат |
|----------|-----------|
| `mail.lancloud.ru:443` | OPEN |
| EWS login `migration_svc@rubda.ru` | **Invalid credentials** |
| SharePoint DNS | жив |

Пароль в `email_migration/.env` **протух** (проверено ранее и повторно 15.10.2026).

---

## 6. Yandex Cloud API

- Файл `CI/TF/yc-sa-key.json` — **не** JSON-ключ сервисного аккаунта для `yc`, а **статический ключ Object Storage** (`access_key` / `secret`) с описанием *«Key for S3 sbx-sys-infra bucket»*. Через `yc compute instance list` им **не** залогиниться.
- На машине проверки активный профиль `yc` указывал на **другой** cloud/folder — folder песочницы АБД из CLI на момент проверки **не открывался**.
- Актуальный список ВМ — через консоль YC или валидный SA key / федерацию организации АБД.

---

## 7. Calendar Bridge (локальный продукт)

Код в `calendar_bridge/`. Назначение: входящие «битые» приглашения → события CalDAV; исходящие `.ics` внешним доменам.

Админка (когда поднят docker): `http://localhost:8091`, пароль admin из `.env`.

Тестовый гайд: `calendar_bridge/TESTING_GUIDE.md`.

**Не проверялся live в этой сессии** (сервис мог быть выключен на машине).

---

## 8. Что считать «аудитом», который уже есть

Полный текстовый аудит архитектуры уже собран ранее и лежит здесь:

→ **`docs/docs_pesochinca_from_meeting.md`** (15 разделов: стек, ВМ, SG, playbooks, VPN, SSO, boto-прокси, долги, quick start).

Этот файл (`01_AUDIT_LIVE_CHECK_…`) — **дополнение на дату передачи**: что реально отвечает снаружи сейчас.

Смежный план работ: `docs/plan_calendar_abd.md`.
