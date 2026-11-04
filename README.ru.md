# NetBox Prefix Map

[![CI](https://github.com/islepnev/netbox-prefix-map/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/islepnev/netbox-prefix-map/actions/workflows/ci.yml)
[![NetBox 4.x](https://img.shields.io/badge/NetBox-4.x-blue)](#требования)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

**Карта мира для вашего адресного пространства IPv4.** Каждый адрес — ячейка, каждая подсеть — прямоугольник, каждый арендатор нарисован своим цветом, от /8 до отдельного адреса. Карты строятся по данным [NetBox](https://github.com/netbox-community/netbox) и перерисовываются, когда NetBox сообщает об изменении через webhook.

![Карта /17: блоки арендаторов, занятые адреса, закреплённый свободный адрес с цепочкой префиксов и свободными блоками](docs/img/hero.ru.png)

## Как читать карту

Адреса идут по Z-кривой (порядок Мортона): первая половина префикса — верхняя или левая половина карты, первая четверть — левая верхняя четверть и так далее. Поэтому любая выровненная подсеть — прямоугольник: /24 на карте /16 — квадрат 16 × 16, /25 — его половина. Серые числа на карте — октеты, по которым эти квадраты различаются, например третий октет каждой /24.

![Z-порядок в /27: адреса от 0 до 31, /30, /29 и /28 — прямоугольники](static/img/z-order.ru.svg)

Одно и то же пространство на трёх уровнях, как при печати:

| /8: ячейка на /24 | /16: ячейка на адрес | /24 |
|---|---|---|
| ![Карта блоков 10.0.0.0/8](docs/img/level-8.png) | ![Карта 10.20.0.0/16](docs/img/level-16.png) | ![Карта 10.20.50.0/24](docs/img/level-24.png) |

## Поиск, ссылки, печать

- **Поиск.** Адреса и префиксы, а также текст в DNS-именах, описаниях, именах арендаторов и ролей, во всех VRF. `свободные /26` (или `free /26`) — свободные блоки /26 во всех VRF, `свободные /26 в 10.20.0.0/16` — внутри префикса.
- **Ссылки.** Адрес страницы хранит закреплённый адрес и выделенного арендатора. `?lang=en` открывает страницу на английском; иначе язык берётся из браузера.
- **Печать.** Ctrl+P печатает только карту, в векторе, с заголовком и легендой; в чёрно-белом варианте арендаторы заштрихованы.

## Требования

- NetBox 4.x и API-токен с правом чтения IPAM (префиксы, IP-адреса, VRF; роли, диапазоны IP и VLAN — по желанию), Tenancy (арендаторы) и по желанию DCIM (сайты, локации, регионы, группы сайтов)
- Docker с Compose или Python 3.13

## Настройка

Параметры читаются из окружения или из файла `.env` в каталоге проекта.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `NETBOX_API_URL` | | Базовый URL NetBox, например `https://netbox.example.com` |
| `NETBOX_API_TOKEN` | | API-токен |
| `NETBOX_TIMEOUT` | `30` | Таймаут запроса к API, секунды |
| `BASE_PATH` | `/prefix-map` | Префикс пути веб-интерфейса, чтобы делить хост с NetBox |
| `OUTPUT_DIR` | `output` | Каталог результатов; относительный путь отсчитывается от каталога проекта |
| `CELL_SIZE` | `4` | Размер ячейки в пикселях изображения |
| `WEBHOOK_SECRET` | | Общий секрет webhook в NetBox; если задан, неподписанные запросы отклоняются |
| `UPDATE_DEBOUNCE_SECONDS` | `60` | Серия webhook даёт одно обновление сразу и не более одного повторного через этот интервал |
| `UPDATE_INTERVAL_SECONDS` | `0` | Периодическое полное обновление, если за это время не было другого, не чаще `UPDATE_DEBOUNCE_SECONDS`; `0` — выключено |
| `INITIAL_UPDATE` | `1` | `0` — не обновлять при запуске |
| `PORT` | `5000` | Порт |

## Запуск

```bash
make up
```

Контейнер сразу отвечает на запросы и строит карты в фоне; они появляются, когда закончится первое обновление. Результаты хранятся в томе `output`.

Без Docker:

```bash
pip install -r requirements.txt
python -m app.cli       # разовое обновление
python -m app.webapp    # сервер для разработки
```

## Настройка NetBox

### Webhook

1. Operations › Integrations › Webhooks › Add: URL `http://<host>:5000/prefix-map/webhook`, метод `POST`, content type `application/json`, секрет как в `WEBHOOK_SECRET`.
2. Operations › Integrations › Event Rules › Add: типы объектов IPAM › Prefix, IPAM › IP Address, IPAM › IP Range, IPAM › VRF, Tenancy › Tenant; при желании IPAM › Role, IPAM › VLAN, DCIM › Site, Location, Region, Site Group, чтобы видеть переименования; события created, updated, deleted; действие — webhook из п. 1.

Если IP-адреса меняются часто и пачками, не включайте IPAM › IP Address в правило событий: NetBox ставит в очередь отдельную задачу webhook на каждый изменённый объект. Вместо этого задайте `UPDATE_INTERVAL_SECONDS` (например, `900`): изменения адресов попадут на карты в пределах этого интервала, а webhook на остальные объекты по-прежнему обновит их сразу.

### Кнопка карты на странице префикса

Customization › Custom Links › Add, тип объекта IPAM › Prefix:

- Link text: `Map`
- Link URL:

  ```
  /prefix-map/map/{{ object.vrf.pk if object.vrf else 'None' }}/{{ (object.prefix | string).replace('.', '_').replace('/', '_') }}
  ```

## Обратный прокси и доступ

Карты показывают все префиксы, IP-адреса, DNS-имена, арендаторов и описания, доступные токену API. Своего входа у приложения нет: ограничьте доступ на обратном прокси. Apache, в виртуальном хосте NetBox:

```apache
<Location /prefix-map>
    ProxyPass http://localhost:5000/prefix-map
    ProxyPassReverse http://localhost:5000/prefix-map
    AuthType Basic
    AuthName "Prefix Map"
    AuthUserFile /etc/apache2/prefix-map.htpasswd
    Require valid-user
</Location>
<Location /prefix-map/webhook>
    Require ip 127.0.0.1 ::1
</Location>
```

Webhook должен оставаться доступным для NetBox: укажите в `Require ip` адрес хоста NetBox, если это не localhost. Без `WEBHOOK_SECRET` любой, кто достучится до `/webhook`, может запустить полную загрузку из NetBox (не чаще раза в `UPDATE_DEBOUNCE_SECONDS`). `/healthz` и `/metrics` не содержат данных инвентаря; `/errors` показывает строки журнала, держите его за тем же правилом, что и карты.

## Адреса

Пути указаны относительно `BASE_PATH`.

| Путь | Назначение |
|---|---|
| `/map/<vrf>/<prefix>` | Карта; `<vrf>` — id VRF или `None` для Global, в `<prefix>` точка и `/` заменены на `_` |
| `/search?q=<запрос>` | Поиск, как в строке поиска (JSON) |
| `/webhook` | Приём webhook NetBox |
| `/healthz` | Состояние и возраст данных (JSON); используется healthcheck контейнера |
| `/metrics` | Метрики Prometheus |
| `/errors` | Последние предупреждения и ошибки |

## Ограничения

- Только IPv4; IPv6-префиксы пропускаются.
- 16 цветов арендаторов по id: у арендаторов, чьи id отличаются на 16, цвет общий.
- Префиксы короче /16 показываются по ячейке на выровненный блок, не более 65 536 ячеек.
- Обновление выполняется внутри веб-процесса; нужен один рабочий процесс веб-сервера.

## Разработка

```bash
make test    # без сети, на синтетических данных из tests/synthetic_data.py
make lint    # flake8, также в CI
```

Устройство приложения: [docs/design.md](docs/design.md). Тексты интерфейса — в `app/locales/<язык>.json` и `templates/_help_<язык>.html`; чтобы добавить язык, переведите копии английских файлов и добавьте код в `LANGUAGES` в `app/i18n.py`.

Вклад принимается на условиях Apache License 2.0, как и весь проект.

## Лицензия

Apache License 2.0, см. [LICENSE](LICENSE). Копии и производные работы должны сохранять уведомление об авторских правах и файл [NOTICE](NOTICE) с именем автора, Ilia Slepnev.
