from time import perf_counter

import folium
from django import forms
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.timezone import localdate
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_http_methods

from . import offers, utils

AIRPORT_CHOICES = [
    (code, f"{code} · {utils.G.nodes[code]['name']}")
    for code in utils.connected_airports
]


class RouteForm(forms.Form):
    source_airport = forms.ChoiceField(
        label="Departure",
        choices=[("", "Select departure airport"), *AIRPORT_CHOICES],
        error_messages={"invalid_choice": "Choose a departure airport from the list."},
    )
    destination_airport = forms.ChoiceField(
        label="Arrival",
        choices=[("", "Select arrival airport"), *AIRPORT_CHOICES],
        error_messages={"invalid_choice": "Choose an arrival airport from the list."},
    )

    def clean(self):
        cleaned_data = super().clean()
        source = cleaned_data.get("source_airport")
        if source and source == cleaned_data.get("destination_airport"):
            self.add_error("destination_airport", "Choose an arrival airport different from your departure.")
        return cleaned_data


class FlightOfferForm(forms.Form):
    source = forms.RegexField(
        r"^[a-zA-Z]{3}\Z", label="Departure IATA code", max_length=3,
        widget=forms.TextInput(attrs={"placeholder": "ABE"}),
    )
    destination = forms.RegexField(
        r"^[a-zA-Z]{3}\Z", label="Arrival IATA code", max_length=3,
        widget=forms.TextInput(attrs={"placeholder": "ATL"}),
    )
    date = forms.DateField(
        label="Departure date", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    preferences = forms.CharField(
        label="Preferences (optional)", required=False, max_length=160,
        help_text="Gemini extracts a price limit or maximum number of stops from this text.",
        widget=forms.TextInput(attrs={"placeholder": "Under ₹20,000 with at most one stop"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].widget.attrs["min"] = localdate().isoformat()
        if not settings.GEMINI_API_KEY:
            self.fields.pop("preferences")

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source", "").upper()
        destination = cleaned.get("destination", "").upper()
        if source and source == destination:
            self.add_error("destination", "Choose an arrival airport different from your departure.")
        if source:
            cleaned["source"] = source
        if destination and "destination" in cleaned:
            cleaned["destination"] = destination
        if cleaned.get("date") and cleaned["date"] < localdate():
            self.add_error("date", "Choose today or a future departure date.")
        return cleaned


@require_http_methods(["GET", "POST"])
@never_cache
def flight_offers_view(request):
    provider_token = settings.DUFFEL_ACCESS_TOKEN
    initial = {field: request.GET.get(field, "") for field in ("source", "destination")}
    form = FlightOfferForm(request.POST if request.method == "POST" else None, initial=initial)
    context = {"form": form, "provider_configured": bool(provider_token)}
    if request.method != "POST" or not form.is_valid():
        return render(request, "routes/offers.html", context)

    source = form.cleaned_data["source"]
    destination = form.cleaned_data["destination"]
    date = form.cleaned_data["date"]
    preferences = form.cleaned_data.get("preferences", "")
    notices = []
    if provider_token and request.POST.get("demo") != "1":
        try:
            flight_offers = offers.fetch_offers(source, destination, date, provider_token)
            offer_source = (
                "Duffel test offers · sample prices" if provider_token.startswith("duffel_test_")
                else "Live Duffel offers"
            )
        except offers.ProviderError:
            notices.append("Duffel is unavailable. Showing fictional demo offers for comparison.")
            flight_offers = offers.demo_offers()
            offer_source = "Demo · sample prices"
    else:
        flight_offers = offers.demo_offers()
        offer_source = "Demo · sample prices"

    if preferences and flight_offers:
        try:
            price, currency, stops = offers.preference_filters(preferences)
            if price is not None and currency is None:
                currencies = {offer.currency for offer in flight_offers}
                if len(currencies) == 1:
                    currency = currencies.pop()
                else:
                    notices.append("Include a currency in your preference to apply a price limit.")
                    price = None
            if price is not None:
                flight_offers = [
                    offer for offer in flight_offers
                    if offer.currency == currency and offer.amount <= price
                ]
                notices.append(f"Price limit applied: {currency} {price:,.2f}.")
            if stops is not None:
                flight_offers = [offer for offer in flight_offers if offer.stops <= stops]
                notices.append(f"Maximum stops applied: {stops}.")
            if price is None and stops is None:
                notices.append("No price or stop limit was applied.")
        except offers.ProviderError:
            notices.append("Gemini preferences are unavailable. Showing all offers.")

    context.update(
        searched=True, source=source, destination=destination, date=date,
        offer_source=offer_source, notices=notices,
        flight_offers=sorted(flight_offers, key=lambda offer: (offer.currency, offer.amount)),
    )
    return render(request, "routes/offers.html", context)


def route_map(path):
    first_airport = utils.G.nodes[path[0]]
    chart = folium.Map(location=(first_airport["lat"], first_airport["lon"]))
    coordinates = []
    previous_lon = first_airport["lon"]
    for code in path:
        airport = utils.G.nodes[code]
        # Keep each leg on the closest copy of the map when crossing the date line.
        lon = previous_lon + (airport["lon"] - previous_lon + 180) % 360 - 180
        point = (airport["lat"], lon)
        coordinates.append(point)
        folium.CircleMarker(
            point, radius=5, color="#07554b", fill=True, fill_color="#21a389",
            fill_opacity=1, tooltip=code,
        ).add_to(chart)
        previous_lon = lon

    folium.PolyLine(coordinates, color="#087e70", weight=4, opacity=0.9).add_to(chart)
    chart.fit_bounds(coordinates, padding=(40, 40), max_zoom=9)
    return chart.get_root().render()


def render_route(request, *, lab=False):
    form = RouteForm(request.POST if request.method == "POST" else None)
    context = {"form": form, "lab": lab, "network_available": bool(AIRPORT_CHOICES)}
    if request.method != "POST" or not AIRPORT_CHOICES or not form.is_valid():
        return render(request, "routes/index.html", context)

    source = form.cleaned_data["source_airport"]
    destination = form.cleaned_data["destination_airport"]
    algorithms = [
        ("A* search", utils.get_astar_path),
        ("Dijkstra", utils.get_dijkstra_path),
    ]
    if lab:
        algorithms.append(("Q-learning", utils.get_rl_path))

    results = []
    for label, find_path in algorithms:
        start = perf_counter()
        result = find_path(source, destination)
        elapsed_ms = (perf_counter() - start) * 1000
        if not results and result is None:
            context["search_error"] = (
                f"No route in the dataset connects {source} and {destination}. "
                "Try an airport in the same route network."
            )
            return render(request, "routes/index.html", context)
        results.append({"label": label, "elapsed_ms": elapsed_ms, "route": result})

    route = results[0]["route"]
    context.update(
        results=results,
        source=source,
        destination=destination,
        stops=len(route["path"]) - 2,
        map_url=reverse("route-map", args=[source, destination]),
    )
    return render(request, "routes/index.html", context)


@require_http_methods(["GET", "POST"])
def find_route_view(request):
    return render_route(request)


@require_http_methods(["GET", "POST"])
def find_route_offline_view(request):
    return render_route(request, lab=True)


@require_http_methods(["GET", "HEAD"])
@xframe_options_sameorigin
def route_map_view(request, source, destination):
    if source == destination:
        return HttpResponse("Choose two different airports.", status=404)
    result = utils.get_astar_path(source, destination)
    if result is None:
        return HttpResponse("No route map is available.", status=404)
    return HttpResponse(route_map(result["path"]))
