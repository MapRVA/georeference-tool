from rest_framework.pagination import PageNumberPagination
from rest_framework_gis.pagination import GeoJsonPagination


class DefaultPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 100


class GeoJsonDefaultPagination(GeoJsonPagination):
    page_size_query_param = "page_size"
    max_page_size = 100
