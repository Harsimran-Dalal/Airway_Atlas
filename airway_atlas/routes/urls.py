from django.urls import path

from . import views

urlpatterns = [
    path("", views.find_route_view, name="home"),
    path("offline/", views.find_route_offline_view, name="offline"),
    path("offers/", views.flight_offers_view, name="flight-offers"),
    path("map/<str:source>/<str:destination>/", views.route_map_view, name="route-map"),
]
