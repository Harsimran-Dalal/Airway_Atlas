import json
from datetime import timedelta
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils.timezone import localdate

from . import offers


class RouteSearchTests(SimpleTestCase):
    def search(self, source, destination, page="home"):
        return self.client.post(
            reverse(page),
            {"source_airport": source, "destination_airport": destination},
        )

    def test_home_lists_airport_names_and_profile(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Airway Atlas")
        self.assertContains(response, "Harsimran Singh Dalal")
        self.assertContains(response, "https://github.com/Harsimran-Dalal")
        self.assertContains(response, "SFO · San Francisco International Airport")
        self.assertContains(response, "ABE · Lehigh Valley International Airport")
        self.assertNotContains(response, 'value="AAB"')

    def test_direct_route_from_abe(self):
        response = self.search("ABE", "ATL")
        self.assertContains(response, "Direct connection")
        self.assertEqual(response.context["results"][0]["route"]["path"], ["ABE", "ATL"])

    def test_route_search_preserves_selection_and_compares_distances(self):
        response = self.search("JFK", "KTM")
        self.assertContains(response, "A* search")
        self.assertContains(response, "Dijkstra")
        self.assertContains(response, 'value="JFK" selected')
        self.assertContains(response, 'value="KTM" selected')
        route, comparison = response.context["results"]
        self.assertAlmostEqual(route["route"]["distance"], comparison["route"]["distance"])
        self.assertGreater(response.context["stops"], 0)
        self.assertContains(response, reverse("route-map", args=["JFK", "KTM"]))
        self.assertContains(response, f'{reverse("flight-offers")}?source=JFK&amp;destination=KTM')

    def test_invalid_airports_display_actionable_errors(self):
        self.assertContains(self.search("SFO", "SFO"), "Choose an arrival airport different")
        self.assertContains(self.search("unknown", "SFO"), "Choose a departure airport from the list.")
        self.assertContains(self.search("AAB", "ABE"), "Choose a departure airport from the list.")
        self.assertContains(self.search("", "SFO"), "This field is required.")

    def test_unconnected_airports_display_a_message(self):
        response = self.search("BLD", "SFO")
        self.assertContains(response, "No route in the dataset connects BLD and SFO.")
        self.assertNotContains(response, "<iframe")

    def test_lab_shows_experimental_result(self):
        response = self.search("DEL", "BOM", page="offline")
        self.assertContains(response, "Algorithm Lab")
        self.assertContains(response, "Q-learning")
        self.assertEqual(len(response.context["results"]), 3)
        self.assertEqual(response.context["results"][2]["route"]["path"], ["DEL", "BOM"])

    def test_lab_explains_when_q_learning_does_not_find_a_route(self):
        with patch("routes.utils.get_rl_path", return_value=None):
            response = self.search("DEL", "BOM", page="offline")
        self.assertContains(response, "No route found within the training budget.")

    def test_map_can_be_embedded_and_crosses_the_date_line(self):
        response = self.client.get(reverse("route-map", args=["DEL", "SFO"]))
        self.assertContains(response, "L.polyline")
        self.assertContains(response, "237.")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        missing = self.client.get(reverse("route-map", args=["HFN", "SFO"]))
        self.assertEqual(missing.status_code, 404)


@override_settings(DUFFEL_ACCESS_TOKEN="", GEMINI_API_KEY="")
class FlightOfferTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("flight-offers")
        self.departure = localdate() + timedelta(days=3)
        self.data = {"source": "del", "destination": "bom", "date": self.departure.isoformat()}

    @patch("routes.offers.requests.post")
    def test_demo_requires_no_keys_or_network(self, post):
        initial = self.client.get(self.url, {"source": "DEL", "destination": "BOM"})
        self.assertContains(initial, 'value="DEL"')
        self.assertContains(initial, 'type="date"')
        self.assertNotContains(initial, 'name="preferences"')
        response = self.client.post(self.url, self.data)
        self.assertContains(response, "Demo · sample prices")
        self.assertContains(response, "Sample Air")
        self.assertContains(response, 'data-sort="price"')
        self.assertContains(response, 'data-sort="minutes"')
        self.assertContains(response, 'data-sort="stops"')
        self.assertEqual(response.context["source"], "DEL")
        self.assertTrue(response.has_header("Cache-Control"))
        post.assert_not_called()

    @patch("routes.offers.requests.post")
    @override_settings(DUFFEL_ACCESS_TOKEN="duffel_test_fake")
    def test_past_date_and_identical_airports_do_not_call_provider(self, post):
        response = self.client.post(
            self.url, {**self.data, "date": "2000-01-01", "destination": "DEL"}
        )
        self.assertContains(response, "Choose today or a future departure date.")
        self.assertContains(response, "Choose an arrival airport different from your departure.")
        post.assert_not_called()

    @patch("routes.offers.requests.post")
    @override_settings(DUFFEL_ACCESS_TOKEN="duffel_test_fake")
    def test_duffel_offers_use_provider_prices_and_are_labelled_as_test(self, post):
        post.return_value.status_code = 201
        post.return_value.json.return_value = {"data": {"offers": [
            {
                "total_amount": "199.99", "total_currency": "USD", "owner": {"name": "Duffel Airways"},
                "slices": [{"duration": "PT2H30M", "segments": [{}, {}]}],
            },
            {
                "total_amount": "145.40", "total_currency": "USD", "owner": {"name": "Another Airline"},
                "slices": [{"duration": "PT1H50M", "segments": [{}]}],
            },
        ]}}
        response = self.client.post(self.url, self.data)
        self.assertContains(response, "Duffel test offers · sample prices")
        self.assertContains(response, "USD 199.99")
        self.assertContains(response, "150 min")
        self.assertEqual(response.context["flight_offers"][0].airline, "Another Airline")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Duffel-Version"], "v2")
        self.assertEqual(kwargs["json"]["data"]["slices"], [
            {"origin": "DEL", "destination": "BOM", "departure_date": self.departure.isoformat()},
        ])
        self.assertNotContains(response, "duffel_test_fake")

    @patch("routes.offers.requests.post", side_effect=requests.Timeout)
    @override_settings(DUFFEL_ACCESS_TOKEN="duffel_test_fake")
    def test_duffel_timeout_falls_back_to_demo(self, post):
        response = self.client.post(self.url, self.data)
        self.assertContains(response, "Duffel is unavailable")
        self.assertContains(response, "Demo · sample prices")
        self.assertEqual(len(response.context["flight_offers"]), 3)
        post.assert_called_once()

    @patch("routes.offers.requests.post")
    @override_settings(GEMINI_API_KEY="fake-gemini", GEMINI_MODEL="fake-model")
    def test_gemini_extracts_filters_and_django_uses_them(self, post):
        post.return_value.status_code = 200
        filters = {"max_price": 20000, "currency": "INR", "max_stops": 1}
        post.return_value.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": json.dumps(filters)}]}}],
        }
        response = self.client.post(self.url, {**self.data, "preferences": "under ₹20,000"})
        self.assertContains(response, "Price limit applied")
        self.assertContains(response, "Maximum stops applied")
        self.assertEqual(len(response.context["flight_offers"]), 2)
        self.assertEqual(post.call_args.args[0], f"{offers.GEMINI_URL}/fake-model:generateContent")
        self.assertEqual(post.call_args.kwargs["headers"], {"x-goog-api-key": "fake-gemini"})
        self.assertNotContains(response, "fake-gemini")

    @patch("routes.offers.requests.post")
    @override_settings(GEMINI_API_KEY="fake-gemini")
    def test_invalid_gemini_response_keeps_unfiltered_offers(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"candidates": []}
        response = self.client.post(self.url, {**self.data, "preferences": "nonstop"})
        self.assertContains(response, "Gemini preferences are unavailable")
        self.assertEqual(len(response.context["flight_offers"]), 3)
