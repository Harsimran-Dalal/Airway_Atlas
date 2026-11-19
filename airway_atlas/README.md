# Airway Atlas web app

See the [project README](../README.md) for installation, usage, and credits.

Run `uv run --locked --python 3.12 python manage.py test` from this directory to check the route search and map endpoints.

The development server accepts `localhost` and `127.0.0.1` by default. Set `DJANGO_DEBUG=1` for local debugging and `DJANGO_SECRET_KEY` for deployment. Render deployments can use the platform-provided `RENDER_EXTERNAL_HOSTNAME`.
