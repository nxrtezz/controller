# Controller

Controller is a Django web app for Bustimes-based bus alerts. It uses rule cards to monitor a selected operator's fleet, vehicle types, liveries, fuel, routes, newly-added inventory, and changed records.

## Run with Docker

1. Copy `.env.example` to `.env` and set a strong `DJANGO_SECRET_KEY`. Set `DJANGO_ALLOWED_HOSTS` to the domains or LAN IP addresses that will access Controller (for example `192.168.1.106,localhost`).
2. Start the app: `docker compose up --build -d`.
3. Create the first account: `docker compose exec web python manage.py createsuperuser`.
4. Import the full Bustimes catalogue: `docker compose exec web python manage.py import_bustimes`.
5. Open `http://localhost:8417` and sign in.

The web UI listens on port **8417**. The monitor service discovers active-rule operators automatically, polls `vehicles.json` every two minutes, and refreshes fleet and services every ten minutes.

Static assets are served by WhiteNoise directly from the Django container, so no separate web server is required.

When no `.env` value is supplied, Docker permits `localhost`, `127.0.0.1`, and the current LAN address (`192.168.1.106`). Set `DJANGO_ALLOWED_HOSTS` explicitly if your LAN address changes or before exposing Controller beyond a trusted network.

## Development

Install dependencies with `python -m pip install -r requirements.txt`, then run `python manage.py migrate`, `python manage.py createsuperuser`, and `python manage.py runserver 8417`.

The `/admin/` interface manages users. Each rule may post to a Discord webhook as well as creating website activity records.
