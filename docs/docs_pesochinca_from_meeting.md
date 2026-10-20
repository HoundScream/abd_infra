# Проект «Песочница» — сводная документация

## 1. Назначение и контекст

«Песочница» — один из главных продуктов организации; среда для **дата-сайентистов** и работы с данными **поставщиков** (примеры: крупные ритейл/телеком) без выноса данных наружу.

**Текущий статус:**
- инфраструктура **не рабочая**, требуется **восстановление** или **пересоздание**;
- ~**2 года** активного использования в **Yandex Cloud**, затем **остановка** (экономия на ВМ);
- после заморозки: **протухшие сертификаты**, смена **ID образов ОС** в Yandex, часть шагов **вручную** (федерация, boto-прокси в контейнере).

**Стратегическая цель:** не «лишь бы завелось», а **актуальная архитектура на годы**; любой итог потребует **пересертификации** (~год, порядка «больше ляма» руб.).

**Параметры контура** (репозиторий IaC `CI/`):
- домен: **`sandbox.rubda.ru`**, realm Kerberos: **`SANDBOX.RUBDA.RU`**;
- каталог Yandex Cloud (folder): **`b1ge40a4pthgp0qrb8qr`**, cloud: **`b1g9nbvkf50o4fk6bkd8`**;
- подсеть: **`10.128.0.0/24`**, зона **`ru-central1-a`**.

---

## 2. Высокоуровневая архитектура

```
                    [Интернет / внешние API YC]
                              |
                    cpe (OpenConnect, NAT IP)
                    10.128.0.5 / 158.160.51.221
                              |
         +--------------------+--------------------+
         |                    |                    |
      idm (FreeIPA)      sso (Keycloak)      armds01 (XRDP+kiosk)
      10.128.0.10        10.128.0.11         10.128.0.100
         |                    |                    |
         +--------------------+--------------------+
                              |
                      logcltr (journald-remote)
                      10.128.0.6
```

Платформа: **Yandex Cloud**. Внутри — ВМ, VPC, security groups, NAT gateway.

Отдельное облако / контур (**rubda**, «sandbox box») — **федерация** и **S3** с датасетами поставщиков (данные **сохранились**, но **устарели**). В репозитории `CI/` это **не автоматизировано**.

Закрытый контур для дата-сайентистов: без произвольного интернета; доступ к S3/API — через **security groups**, firewall, **прокси boto3** (отдельный сервис, см. § 7).

**DataSphere** + **Jupyter** — основной UX в браузере; вычисления — на **эфемерных ВМ**, создаваемых DataSphere (не описаны в Ansible inventory).

### 2.1. Стек (сводная таблица)

| Компонент | Назначение | В IaC (`CI/`) |
|-----------|------------|---------------|
| Terraform | VPC, SG, Compute | Да, `CI/TF/` |
| Ansible | Конфигурация ОС и сервисов | Да, `CI/playbooks/`, `roles/` |
| FreeIPA (`idm`) | LDAP/Kerberos, DNS, HBAC, PAM | Да |
| Keycloak (`sso`) | SSO, федерация с Yandex | Да (Podman) |
| OpenConnect (`cpe`) | VPN для пользователей и админов | Да (ocserv) |
| StrongSwan | IKEv2 (админ / ARMDS подсети VPN) | Роль есть, **в основных playbooks не вызывается** |
| XRDP + Chromium | ARMDS, kiosk | Да |
| systemd journal remote/upload | Централизация логов | Да, роль `journald` |
| boto3-прокси к S3 | Подмена creds на SA | **Нет** |
| Jenkins / GitLab CI для песочницы | — | **Нет** |
| Neocat, «гостовый VPN» | Сканер / legacy VPN | **Нет** (только в облаке вручную) |

---

## 3. Репозиторий `CI/` — структура

| Путь | Содержимое |
|------|------------|
| `TF/` | Terraform: сеть, 5 ВМ (+ закомментированный `nat`) |
| `TF/___back___/` | Архив **другого** проекта (`pudra-infra`, K8s, Kafka…) — **не относится к песочнице** |
| `playbooks/` | 8 основных + 2 optional playbooks |
| `roles/` | bootstrap, ipaserver, ipaclient, openconnecthost, strongswanhost, keycloak, podmanhost, armdshost, journald |
| `inventory/` | `hosts.yml`, `group_vars/`, `host_vars/` |
| `library/` | Кастомные модули FreeIPA, Podman |
| `ansible.cfg` | Конфиг Ansible (см. § 12) |

В репозитории также могут храниться чувствительные данные (пароли, токены, ключи) — при восстановлении нужна **ротация**, исключение секретов из git.

---

## 4. Инвентарь и виртуальные машины

### 4.1. Хосты Ansible (`inventory/hosts.yml`)

| Host | Группы | FQDN | IP (internal) | Образ YC (`yc_vm_image_id`) | vCPU/RAM/диск (playbook 01) |
|------|--------|------|---------------|-----------------------------|------------------------------|
| **idm** | ipaserver, ipaclients* | idm.sandbox.rubda.ru | 10.128.0.10 | `fd88q0bhq1dnc8iro935` (AlmaLinux) | 4 / 8 GB / 140 GB |
| **sso** | ssoserver, ipaclients | sso.sandbox.rubda.ru | 10.128.0.11 | `fd8tgblovu5dklvrp29h` (Ubuntu) | 2 / 4 GB / 20 GB, NAT |
| **cpe** | vpnserver, ipaclients | cpe.sandbox.rubda.ru | 10.128.0.5 | Ubuntu | 2 / 2 GB / 10 GB, NAT **158.160.51.221** |
| **armds01** | armdshosts, ipaclients | armds01.sandbox.rubda.ru | 10.128.0.100 | Ubuntu | 4 / 16 GB / 80 GB |
| **logcltr** | ipaclients | logcltr.sandbox.rubda.ru | 10.128.0.6 | Ubuntu | 2 / 6 GB / 200 GB |
| ~~nat~~ | *(закомментирован)* | nat.sandbox.rubda.ru | — | — | — |

\* После playbook 05 хосты (кроме idm) становятся клиентами FreeIPA.

Маршруты VPN-клиентов (`10.255.255.0/25`, `10.255.255.128/25`) в Terraform указывают **next_hop 10.128.0.5** — это **внутренний IP `cpe`**, не отдельный `nat` (хост `nat` в inventory **отключён**).

### 4.2. Компоненты и роли

| Компонент | Реализация |
|-----------|------------|
| VPN OpenConnect | `cpe`, роль `openconnecthost` |
| SSO / Keycloak | `sso`, Keycloak **18.0.2** + PostgreSQL **15** (Podman) |
| FreeIPA | `idm` |
| ARMDS (рабочее место DS) | `armds01`, XRDP + **chromium-browser** |
| Сбор логов | `logcltr`, `setup_journald_collector: yes` |
| Neocat (сканер) | Только в консоли YC, **не в Terraform/Ansible** |
| «Гостовский» VPN | Только в консоли YC, **не в IaC** |

### 4.3. Security groups (Terraform `vpc.tf`)

| SG | Смысл |
|----|--------|
| `vpn_server_sg` | SSH 22, HTTP 80 (certbot), **443** (OpenConnect) с 0.0.0.0/0 |
| `sso_server_sg` | **8443** (Keycloak/SSO) с 0.0.0.0/0 |
| `default_local_network_sg` | Внутренняя сеть 10.128.0.0/24, 10.255.255.0/25 |
| `armds_users_sg` | RDP **3389**; egress — whitelist сетей (Yandex, Megafon и др.) |

Для DataSphere в браузере нужен доступ к API/ресурсам Yandex Cloud — в IaC не зафиксирован построчно, настраивалось через security groups и оперативные правки.

---

## 5. Pipeline развёртывания (Ansible playbooks)

Ansible **вызывает Terraform** (`community.general.terraform`) из playbook **01** (единая точка старта, не разделение state по слоям).

| № | Файл | Действие |
|---|------|----------|
| 01 | `01.setup_yc_base_infra.yml` | TF: VPC, subnet, NAT GW, route table, SG; ВМ cpe/idm/sso/armds01/logcltr; на **cpe** — bootstrap + **openconnecthost** |
| 02 | `02.bootstrap.yml` | bootstrap на всех хостах |
| 03 | `03.install-logs-collector.yml` | journald на **logcltr** |
| 04 | `04.install-ipa-server.yml` | ipaserver + journald на **idm** |
| 05 | `05.install-ipa-client.yml` | ipaclient + journald на клиентах |
| 06 | `06.configure-ipa-server.yml` | HBAC, группы, example-пользователи, политики паролей |
| 07 | `07.install-sso-server.yml` | podmanhost + **keycloak** на **sso** |
| 08 | `08.install-armds-hosts.yml` | **armdshost** (XRDP) на **armds01** |
| 99 | `99-optional.install-journal-upload.yml` | journal upload на хостах |
| 99 | `99-optional.install-vpn-server.yml` | только openconnecthost (дубль) |

Пользователь автоматизации: **`svc_iac_sa`** (`inventory/group_vars/all/defaults.yml`).

Отдельного **Jenkins** для песочницы нет; токен Yandex Cloud передаётся через переменные Ansible.

---

## 6. Авторизация и доступ

### 6.1. FreeIPA (`idm`)

Kerberos, **PAM**, **SSSD**; DNS на idm (`10.128.0.10`).

Playbook `06.configure-ipa-server.yml`:
- удаляется HBAC **`allow_all`**;
- сервисы: **`ocserv`**, **`xrdp-sesman`**;
- группы: `data_owners`, `data_providers`, `data_scientists`, `admins`, `data_protection_officers`, `armds_terminal_users`, `armds_terminal_administrators`, `cpe_vpn_access_users`;
- hostgroups: `vpn_servers` (cpe), `armds_hosts` (armds01).

Пользователей дата-сайентистов заводили **вручную в FreeIPA** (без корпоративного IDM); выдача паролей — по регламенту, одноразовые ссылки (аналог pass/secret).

### 6.2. VPN

Основной путь в автоматизации: **OpenConnect (ocserv)** на `cpe`, PAM → FreeIPA, Let's Encrypt (`certbot`).

Дополнительно в коде: роль **`strongswanhost`**, `inventory/group_vars/vpnserver/ipsec_connections.yml`:
- **`ikev2-iac-sa`** — `@raas.sandbox.rubda.ru`, клиенты `10.255.255.0/25`;
- **`armds-users`** — `@cpe.sandbox.rubda.ru`, доступ к RDP 3389, idm https, sso 8443, DNS; клиенты `10.255.255.128/25`.

StrongSwan **не входит** в цепочку playbooks 01–08 (только OpenConnect).

### 6.3. SSO / Keycloak (`sso`)

Keycloak ↔ федерация **Yandex Cloud** ↔ FreeIPA — **критичный ручной шаг** (выгрузка SSL из FreeIPA в федерацию Yandex).

Образ: `quay.io/keycloak/keycloak:18.0.2`, PostgreSQL 15, `network: host`, сертификаты с idm (`/etc/ipa/certs`).

### 6.4. Сценарий дата-сайентиста

1. VPN **OpenConnect** на `cpe` (логин/пароль = учётка FreeIPA).
2. **RDP** на `armds01` (порт 3389).
3. Kiosk **Chromium** → Yandex Cloud / **DataSphere**.
4. Те же учётные данные → запросы через **boto3** к данным (через **прокси**, см. § 7).

Запрещены **буфер обмена** и **проброс** устройств в RDP-сессии.

XRDP: `TerminalServerUsers: armds_terminal_users`, `TerminalServerAdmins: armds_terminal_administrators`.

---

## 7. Данные поставщиков и boto3-прокси

Раздел описывает рабочий контур; **исходный код прокси в `CI/` отсутствует**.

- S3 в отдельном облаке rubda; каталоги поставщиков (alpha data, beeline, brand logic, dit moscow, ertst, yang и др.);
- данные в основном **обезличенные**; пример — «пешеходные потоки» (CSV, геокоординаты, тепловые карты);
- **boto3-прокси**: проверка пользователя (FreeIPA), подмена на **per-user service account**, права только на разрешённые бакеты;
- исторически: Python 2 → 3, шлюз на Windows → Linux; план — **контейнер** + логи обращений к бакетам;
- с ARMDS прямой доступ к S3 **закрыт**, открыт только прокси.

Object Storage в Yandex Cloud доступен по **внешнему IP** — ограничения обходятся через security groups и точечные правила.

---

## 8. Логирование

| Уровень | Реализация |
|---------|------------|
| Логи с ВМ | `logcltr`, роль `journald`, journal-remote |
| Облако | Audit Trails (не в Terraform) |
| boto-прокси | Планируется логирование обращений к бакетам |
| ELK / Grafana | Планировались, не внедрены как единый контур |

---

## 9. История проекта

1. **Windows**: AD, RDP, шлюз, Docker Registry, тяжёлый образ (sklearn, PyTorch и др.).
2. Проблема **лицензий Windows** → миграция на **Linux / open-source**.
3. **FreeIPA** вместо Samba AD; **AlmaLinux** на `idm` (отдельный image id, в отличие от Ubuntu на остальных хостах).
4. Заморозка → протухшие сертификаты, смена image ID в Yandex Cloud, изменения UI/CLI Yandex.
5. При восстановлении остаётся порядка **50% ручных шагов**.

Keycloak и PostgreSQL сейчас через **Podman**, не «голый Docker» первой версии.

---

## 10. Компоненты вне репозитория IaC

| Компонент | Описание |
|-----------|----------|
| **Neocat** | Сканер уязвимостей облака; обычно выключен; почасовая оплата |
| **«Гостовский» VPN** | Legacy для администраторов; избыточен при раздельных точках входа |
| **4 бакета Object Storage** | ПНР, разграничение доступа по пользователям |
| **7 образов marketplace + ISO в S3 Distributions** | Артефакты развёртывания |
| **boto3-прокси** | Отдельная разработка; контейнер и логи — не доделаны |
| **DataSphere, эфемерные compute** | Вне Ansible inventory |

---

## 11. Нагрузка и экономика

- Ориентир: ~**5** одновременных пользователей на постоянном контуре (VPN, RDP, авторизация).
- Вычисления DataSphere — на отдельных краткоживущих ВМ.
- **Прерываемые ВМ** не подходят для RDP (риск обрыва сессии).
- **Бронирование** ресурсов на год — экономия порядка **30–40%**.
- **Non-100% vCPU** использовали где возможно; критичные сервисы (логи, auth) — на стабильных SKU.
- **Neocat** — включать только на время сканирования.

Платформа ВМ в IaC: `standard-v1`; NAT включён на **cpe** и **sso**.

---

## 12. Замечания по репозиторию `CI/` (для восстановления)

| Проблема | Где |
|----------|-----|
| `default_tf_project_path` = `/Users/ext/ARMDC/CI/TF` | `inventory/group_vars/all/defaults.yml` — на другой машине не сработает |
| `ansible.cfg`: `hostfile = inventory` | Должно быть `inventory = inventory` |
| Секреты в открытом виде | `secrets.yml`, `oauth`, `TF/yc-sa-key.json`, `terraform.tfstate` |
| Нет remote state Terraform | `TF/provider.tf` |
| Все ВМ делят одни TF-переменные | риск при полном `terraform apply` |
| `nat` закомментирован, маршруты на 10.128.0.5 | `vpc.tf`, `hosts.yml` |
| StrongSwan не в основном pipeline | только роль |
| boto3-прокси отсутствует | отдельная задача |
| `TF/___back___/` | чужой проект, не путать с песочницей |

---

## 13. Незавершённая работа и развилка

**Обязательно доделать или принять решение:**
1. Федерация **Yandex Cloud ↔ Keycloak / FreeIPA** (SSL).
2. **Контейнер boto3-прокси** + логирование обращений к Object Storage.
3. **Восстановить** текущий IaC или **пересоздать** инфраструктуру (сроки, стоимость, пересертификация).

**План восстановления:**
- доступ в Yandex Cloud и репозиторий `CI/`;
- последовательный прогон playbooks 01–08, фиксация ошибок;
- вердикт и предложения по улучшению архитектуры.

| Вариант | Когда уместен |
|---------|----------------|
| **A. Восстановить IaC** | Код близок к рабочему, правки точечные |
| **B. Пересоздать** | Дольше устранять drift, чем переписать с нуля |

---

## 14. Открытые вопросы (не зафиксированы в IaC)

- Точные имена **4 бакетов** Object Storage.
- Репозиторий исходников **boto3-прокси**.
- Пошаговая настройка **федерации** Yandex (сертификаты, IdP URLs).
- Пакет документов **сертификации** (отдельный комплект, по согласованию).
- Актуальное состояние (вкл/выкл) **Neocat** и ghost VPN в консоли.

---

## 15. Быстрый старт восстановления

```bash
cd CI
# исправить default_tf_project_path в inventory/group_vars/all/defaults.yml
# настроить учётные данные Yandex Cloud; ansible-vault для secrets.yml

ansible-playbook -i inventory playbooks/01.setup_yc_base_infra.yml
ansible-playbook -i inventory playbooks/02.bootstrap.yml
# ... playbooks 03–08 по порядку
```

Порядок развёртывания и имена playbooks — в каталоге `CI/playbooks/`.
