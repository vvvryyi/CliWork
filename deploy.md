# Развёртывание Personal CRM на VPS

Инструкция подготовлена для Ubuntu 26.04 и VPS `78.141.223.56`. Проект рассчитан на запуск через Gunicorn за Nginx. Домен и SSH-адрес Git-репозитория пока неизвестны, поэтому в командах используются маркеры `<DOMAIN>`, `<REPOSITORY_SSH_URL>` и `<GIT_HOST>`.

## Принятая схема размещения

Для проекта создаются отдельный системный пользователь, каталог, виртуальное окружение, deploy-ключ и systemd-сервис:

```text
/srv/personal-crm/
├── app/                 # Git-репозиторий
├── venv/                # отдельное Python-окружение
├── deploy-keys/         # отдельный ключ доступа к репозиторию и known_hosts
└── shared/
    ├── .env             # секреты и параметры запуска
    ├── instance/
    │   ├── crm.sqlite3  # база данных
    │   └── uploads/     # загруженные файлы
    └── backups/         # локальные резервные копии
```

Сервис слушает только `127.0.0.1:8010`. Перед установкой нужно убедиться, что этот порт не занят другим проектом. Если занят — выбрать другой порт и одинаково заменить его в systemd и Nginx.

## 1. Первичная подготовка сервера

Подключиться к VPS под существующим администратором:

```bash
ssh <VPS_ADMIN>@78.141.223.56
```

Обновить систему и установить необходимые пакеты:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y python3 python3-venv python3-dev build-essential libpq-dev \
  git nginx curl sqlite3 openssl
```

Создать отдельного системного пользователя без интерактивного входа и каталоги проекта:

```bash
sudo adduser --system --group --home /srv/personal-crm \
  --shell /usr/sbin/nologin personal-crm

sudo install -d -o personal-crm -g personal-crm -m 0750 \
  /srv/personal-crm/app \
  /srv/personal-crm/venv \
  /srv/personal-crm/deploy-keys \
  /srv/personal-crm/shared/instance/uploads \
  /srv/personal-crm/shared/backups
```

Проверить порт приложения:

```bash
sudo ss -ltnp | grep ':8010 ' || true
```

Пустой результат означает, что порт свободен.

## 2. Отдельный SSH deploy-ключ репозитория

Этот ключ нужен только для чтения Git-репозитория. Он не заменяет ключ администратора для входа на VPS и не должен иметь passphrase, иначе автоматическое обновление сервиса потребует ручного ввода.

```bash
sudo -u personal-crm ssh-keygen -t ed25519 \
  -C "personal-crm@78.141.223.56" \
  -f /srv/personal-crm/deploy-keys/repository_ed25519 \
  -N ""

sudo chmod 700 /srv/personal-crm/deploy-keys
sudo chmod 600 /srv/personal-crm/deploy-keys/repository_ed25519
sudo chmod 644 /srv/personal-crm/deploy-keys/repository_ed25519.pub

sudo cat /srv/personal-crm/deploy-keys/repository_ed25519.pub
```

Последнюю выведенную строку нужно добавить в настройках будущего репозитория как **Deploy key** только для чтения. Право на запись этому ключу не требуется.

После получения адреса репозитория определить его хост, например `github.com` или `gitlab.com`, сверить опубликованный провайдером SSH fingerprint и создать отдельный `known_hosts`:

```bash
sudo -u personal-crm ssh-keyscan -H <GIT_HOST> \
  | sudo tee /srv/personal-crm/deploy-keys/known_hosts >/dev/null
sudo chown personal-crm:personal-crm /srv/personal-crm/deploy-keys/known_hosts
sudo chmod 600 /srv/personal-crm/deploy-keys/known_hosts
```

`ssh-keyscan` сам по себе не подтверждает подлинность сервера: fingerprint результата необходимо сравнить с официальной документацией выбранного Git-провайдера.

Клонировать репозиторий:

```bash
sudo -u personal-crm env \
  GIT_SSH_COMMAND="ssh -i /srv/personal-crm/deploy-keys/repository_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/srv/personal-crm/deploy-keys/known_hosts" \
  git clone <REPOSITORY_SSH_URL> /srv/personal-crm/app
```

Если каталог `app` должен быть пустым для клонирования, удалить только созданный пустой каталог командой `sudo rmdir /srv/personal-crm/app`, затем повторить `git clone`. Не помещать deploy-ключ внутрь `/srv/personal-crm/app`: рабочее дерево Git может заменяться при обновлениях.

## 3. Виртуальное окружение и зависимости

```bash
sudo -u personal-crm python3 -m venv /srv/personal-crm/venv
sudo -u personal-crm /srv/personal-crm/venv/bin/python -m pip install --upgrade pip
sudo -u personal-crm /srv/personal-crm/venv/bin/python -m pip install \
  -r /srv/personal-crm/app/requirements.txt
```

Проверить версию Python и Gunicorn:

```bash
sudo -u personal-crm /srv/personal-crm/venv/bin/python --version
sudo -u personal-crm /srv/personal-crm/venv/bin/gunicorn --version
```

## 4. Переменные окружения и постоянные данные

Создать файл секретов:

```bash
sudoedit /srv/personal-crm/shared/.env
```

Содержимое файла:

```dotenv
CRM_USERNAME=admin
CRM_PASSWORD=<LONG_RANDOM_PASSWORD>
SECRET_KEY=<LONG_RANDOM_SECRET>
CRM_TIMEZONE=Europe/Moscow
DATABASE_URL=sqlite:////srv/personal-crm/shared/instance/crm.sqlite3
UPLOAD_FOLDER=/srv/personal-crm/shared/instance/uploads
MAX_CONTENT_LENGTH=20971520
```

Секрет можно сгенерировать командой `openssl rand -hex 32`. Пароль CRM должен быть другим и не должен совпадать с паролем администратора VPS.

Установить владельца и права, затем сделать ссылку на `.env` в рабочем дереве приложения:

```bash
sudo chown personal-crm:personal-crm /srv/personal-crm/shared/.env
sudo chmod 600 /srv/personal-crm/shared/.env
sudo -u personal-crm ln -s ../shared/.env /srv/personal-crm/app/.env
```

`.env`, база и вложения не должны попадать в Git. Они уже исключены текущим `.gitignore` проекта.

Применить миграции:

```bash
cd /srv/personal-crm/app
sudo -u personal-crm /srv/personal-crm/venv/bin/python -m flask \
  --app run.py db upgrade
```

## 5. Systemd-сервис

Создать `/etc/systemd/system/personal-crm.service`:

```bash
sudoedit /etc/systemd/system/personal-crm.service
```

Содержимое:

```ini
[Unit]
Description=Personal CRM Gunicorn service
After=network.target

[Service]
Type=simple
User=personal-crm
Group=personal-crm
WorkingDirectory=/srv/personal-crm/app
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/srv/personal-crm/venv/bin/gunicorn \
    --bind 127.0.0.1:8010 \
    --workers 1 \
    --threads 4 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile - \
    run:app
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGQUIT
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/personal-crm/shared

[Install]
WantedBy=multi-user.target
```

Один worker выбран намеренно: текущая версия использует SQLite и предназначена для одного пользователя. При переходе на PostgreSQL число workers можно увеличить.

Активировать и проверить сервис:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now personal-crm
sudo systemctl status personal-crm --no-pager
curl --fail http://127.0.0.1:8010/healthz
```

Ожидаемый ответ health check:

```json
{"status":"ok"}
```

Логи приложения:

```bash
sudo journalctl -u personal-crm -n 100 --no-pager
sudo journalctl -u personal-crm -f
```

## 6. Nginx и будущий домен Cloudflare

До получения домена не создавать универсальный `default_server`: на VPS уже размещены другие проекты. После получения домена создать отдельный файл `/etc/nginx/sites-available/personal-crm`:

```bash
sudoedit /etc/nginx/sites-available/personal-crm
```

Начальная HTTP-конфигурация:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name <DOMAIN>;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
    }

    location = /healthz {
        proxy_pass http://127.0.0.1:8010/healthz;
        access_log off;
    }
}
```

Заменить `<DOMAIN>` на реальный домен до включения конфигурации, затем выполнить:

```bash
sudo ln -s /etc/nginx/sites-available/personal-crm \
  /etc/nginx/sites-enabled/personal-crm
sudo nginx -t
sudo systemctl reload nginx
```

Проверить выбор правильного virtual host ещё до переключения DNS:

```bash
curl --resolve <DOMAIN>:80:127.0.0.1 http://<DOMAIN>/healthz
```

В Cloudflare потребуется создать DNS-запись `A`, направленную на `78.141.223.56`. Для рабочего режима следует использовать HTTPS и режим SSL/TLS **Full (strict)**. Финальный способ установки сертификата — Let's Encrypt либо Cloudflare Origin Certificate — нужно выбрать после получения домена и сведений о текущей конфигурации Nginx на сервере. Режим **Flexible** использовать не следует.

## 7. Firewall

Перед включением UFW сначала убедиться, что SSH разрешён на фактическом порту сервера. Если SSH использует стандартный порт 22:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status verbose
```

Порт `8010` открывать во внешний мир не нужно: он доступен только через loopback. Если SSH работает не на 22-м порту, вместо профиля `OpenSSH` сначала разрешить реальный порт.

## 8. Обновление проекта

Перед обновлением желательно сделать резервную копию. Затем:

```bash
sudo -u personal-crm env \
  GIT_SSH_COMMAND="ssh -i /srv/personal-crm/deploy-keys/repository_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/srv/personal-crm/deploy-keys/known_hosts" \
  git -C /srv/personal-crm/app pull --ff-only

sudo -u personal-crm /srv/personal-crm/venv/bin/python -m pip install \
  -r /srv/personal-crm/app/requirements.txt

cd /srv/personal-crm/app
sudo -u personal-crm /srv/personal-crm/venv/bin/python -m flask \
  --app run.py db upgrade

sudo systemctl restart personal-crm
curl --fail http://127.0.0.1:8010/healthz
sudo systemctl status personal-crm --no-pager
```

`git pull --ff-only` не затирает неожиданные локальные изменения. На сервере не следует редактировать отслеживаемые Git-файлы вручную.

## 9. Резервное копирование

Для полноценной копии нужны база SQLite, вложения и `.env`. Пример ручной копии:

```bash
BACKUP_DATE="$(date +%Y%m%d-%H%M%S)"

sudo -u personal-crm sqlite3 \
  /srv/personal-crm/shared/instance/crm.sqlite3 \
  ".backup '/srv/personal-crm/shared/backups/crm-${BACKUP_DATE}.sqlite3'"

sudo -u personal-crm tar -C /srv/personal-crm/shared \
  -czf "/srv/personal-crm/shared/backups/files-${BACKUP_DATE}.tar.gz" \
  .env instance/uploads
```

Локальные копии на том же VPS не защищают от потери диска. После запуска проекта следует настроить регулярное шифрованное копирование каталога `shared/backups` на внешний носитель или в объектное хранилище и периодически проверять восстановление.

## 10. Контрольный список

- Репозиторий клонируется отдельным read-only deploy-ключом.
- Приватный deploy-ключ имеет права `600` и не находится в Git-рабочем дереве.
- `.env` имеет права `600`; пароль и `SECRET_KEY` заменены.
- База и вложения находятся в `/srv/personal-crm/shared`, а не в каталоге релиза.
- `flask --app run.py db upgrade` завершён без ошибок.
- `personal-crm.service` активен и запускается после перезагрузки.
- `curl http://127.0.0.1:8010/healthz` возвращает `{"status":"ok"}`.
- Nginx-конфигурация содержит только будущий реальный домен и не конфликтует с другими проектами.
- В Cloudflare задан `A -> 78.141.223.56`, а после установки сертификата включён Full (strict).
- Порт Gunicorn не открыт в UFW.
- Создана и проверена внешняя резервная копия.

## Данные, которые ещё нужны

1. SSH URL репозитория и Git-хост (`github.com`, `gitlab.com` или другой).
2. Основная ветка репозитория, если это не ветка по умолчанию.
3. Домен или поддомен в Cloudflare.
4. Фактический SSH-порт и имя администратора VPS.
5. Подтверждение, свободен ли локальный порт `8010`, либо выбранный альтернативный порт.
6. Выбор TLS-сертификата: Let's Encrypt или Cloudflare Origin Certificate.
