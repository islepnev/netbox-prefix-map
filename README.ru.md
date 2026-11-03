# NetBox Prefix Map

Отображает IPv4-префиксы из [NetBox](https://github.com/netbox-community/netbox) в виде пиксельной сетки: одна ячейка на адрес, порядок ячеек по Z-кривой, поэтому любая выровненная подсеть занимает прямоугольник. Дочерние префиксы закрашены цветом арендатора (tenant), занятые адреса нарисованы поверх. Карты перестраиваются, когда NetBox сообщает об изменениях через webhook.

Веб-интерфейс работает под базовым путём (по умолчанию `/prefix-map`), чтобы делить хост и обратный прокси с NetBox.

## Требования

- NetBox 4.x и API-токен с правом чтения IPAM (префиксы, IP-адреса, VRF, роли) и Tenancy (арендаторы)
- Docker с Compose или Python 3.13

## Настройка

Параметры читаются из окружения или из файла `.env` в каталоге проекта.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `NETBOX_API_URL` | | Базовый URL NetBox, например `https://netbox.example.com` |
| `NETBOX_API_TOKEN` | | API-токен |
| `NETBOX_TIMEOUT` | `30` | Таймаут запроса к API, секунды |
| `BASE_PATH` | `/prefix-map` | Префикс пути веб-интерфейса |
| `OUTPUT_DIR` | `output` | Каталог результатов; относительный путь отсчитывается от каталога проекта |
| `CELL_SIZE` | `4` | Размер ячейки в пикселях |
| `WEBHOOK_SECRET` | | Общий секрет webhook в NetBox; если задан, неподписанные запросы отклоняются |
| `UPDATE_DEBOUNCE_SECONDS` | `60` | Минимальный интервал между обновлениями по webhook |
| `INITIAL_UPDATE` | `1` | `0` — не обновлять при запуске |
| `PORT` | `5000` | Порт |

## Запуск

В Docker:

```bash
make up
```

Контейнер сразу отвечает на запросы и обновляет карты в фоне. Результаты хранятся в томе `output`. `make logs` и `make down` — логи и остановка.

Без Docker:

```bash
pip install -r requirements.txt
python -m app.cli       # разовое обновление
python -m app.webapp    # сервер для разработки
```

## Настройка NetBox

### Webhook

1. Operations › Integrations › Webhooks › Add: URL `http://<host>:5000/prefix-map/webhook`, метод `POST`, content type `application/json`, секрет как в `WEBHOOK_SECRET`.
2. Operations › Integrations › Event Rules › Add: типы объектов IPAM › Prefix, IPAM › IP Address, IPAM › VRF, Tenancy › Tenant; события created, updated, deleted; действие — webhook из п. 1.

События для других типов объектов игнорируются. Серия событий запускает одно обновление сразу и не более одного повторного через `UPDATE_DEBOUNCE_SECONDS`.

### Кнопка карты на странице префикса

Customization › Custom Links › Add, тип объекта IPAM › Prefix:

- Link text: `Map`
- Link URL:

  ```
  /prefix-map/map/{{ object.vrf.pk if object.vrf else 'None' }}/{{ (object.prefix | string).replace('.', '_').replace('/', '_') }}
  ```

## Обратный прокси

Apache, в виртуальном хосте NetBox:

```apache
<Location /prefix-map>
    ProxyPass http://localhost:5000/prefix-map
    ProxyPassReverse http://localhost:5000/prefix-map
</Location>
```

Нужны модули `mod_proxy` и `mod_proxy_http`.

## Адреса

Пути указаны относительно `BASE_PATH`.

| Путь | Назначение |
|---|---|
| `/` | Список VRF |
| `/map/<vrf>/<prefix>` | Карта; `<vrf>` — id VRF или `None` для Global, в `<prefix>` точка и `/` заменены на `_` |
| `/webhook` | Приём webhook NetBox |
| `/healthz` | Состояние и возраст данных (JSON); используется healthcheck контейнера |
| `/metrics` | Метрики Prometheus |
| `/errors` | Последние предупреждения и ошибки |

## Ограничения

- Только IPv4; IPv6-префиксы пропускаются.
- Изображения строятся для префиксов /16 и длиннее. Более короткие доступны только для навигации.
- Обновление выполняется внутри веб-процесса; нужен один рабочий процесс веб-сервера.
- Аутентификации нет; при необходимости ограничьте доступ на обратном прокси.

## Разработка

```bash
make test
```

Тесты работают без NetBox на синтетических данных (`tests/synthetic_data.py`). Устройство приложения: [docs/design.md](docs/design.md).
