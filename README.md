# Airway Atlas

Airway Atlas is a Django app for exploring the shortest paths through a bundled airport network. Enter an airport name or IATA code, search a pair, and see the route on a map alongside results from A* and Dijkstra.

## Run locally

From the repository root, with `uv` installed:

```powershell
cd airway_atlas
uv sync --locked --python 3.12
uv run --locked --python 3.12 python manage.py migrate
uv run --locked --python 3.12 python manage.py runserver
```

Open [the Route Explorer](http://127.0.0.1:8000/). Try **DEL → SFO** for a direct connection or **JFK → KTM** for a route with a connection.

### Run tests

From `airway_atlas/`, run:

```powershell
uv run --locked --python 3.12 python manage.py test
```

### Environment variables

Local development and tests use the bundled CSV data and a development-only Django secret. No `.env` file or API keys are required. To enable local debugging, add `DJANGO_DEBUG=1` to `airway_atlas/.env` next to `manage.py`. For deployment, set a unique `DJANGO_SECRET_KEY` through your hosting provider's environment settings.

## Find flight offers

Open **Flight offers** or use **Find flight offers** beside a route result to prefill the airport codes. Choose a departure date to compare one-way economy offers by price, duration, or number of stops.

- **Demo mode** works without an API token and uses labeled fictional prices. If Duffel is unavailable, the offers page shows demo results with an explanation.
- **Duffel test mode** uses your own sandbox token. Create it under **Access tokens** in **Developer test mode** and add `DUFFEL_ACCESS_TOKEN=duffel_test_...` to your `.env`. For consistent sandbox results, try **JFK → EWR**. [Duffel setup guide](https://duffel.com/docs/guides/getting-started-with-flights)
- **Gemini preferences** are enabled by `GEMINI_API_KEY` or `GOOGLE_API_KEY`. When both are set, `GEMINI_API_KEY` takes precedence. For example, try “under ₹20,000 with at most one stop” in demo mode. Django applies the extracted filters to the offer data. Set `GEMINI_MODEL` to use a different model available to your key.

The app reads `.env` next to `manage.py` and also checks the repository root for values. Restart the Django server after editing either file. The route explorer runs independently of both providers.

## Explore the network

- **Route Explorer** compares A* and Dijkstra by total distance, airport sequence, and runtime for the current search.
- **Algorithm Lab** at `/offline/` adds a reproducible Q-learning experiment. It reports the best route found during training, and some pairs exhaust the training budget before reaching the destination.
- [**Analysis notebook**](Airway_Atlas.ipynb) explores airport centrality, route distances, and algorithm performance.

The app reads the bundled [Airline Routes & Airports dataset](https://www.kaggle.com/datasets/moonnectar/airline-routes-92k-and-airports-10k-dataset) and treats each connection as bidirectional. It minimizes total great-circle distance through the dataset. Use it to explore the network and compare algorithms. Route search runs without API keys. The interactive map and enhanced airport picker load browser assets from the internet.

## Credits

- **Harsimran Singh Dalal** · [GitHub](https://github.com/Harsimran-Dalal)
- Upstream project · [Shivamkhator/SkyBee_Routes](https://github.com/Shivamkhator/SkyBee_Routes)
