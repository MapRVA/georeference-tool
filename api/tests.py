import base64
import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.utils import timezone
from oauth2_provider.models import AccessToken, Application, RefreshToken

from activity.models import (
    GeoreferenceGroup,
    GeoreferenceGroupMember,
    SitewideMilestone,
    UserMilestone,
)
from api.models import ApplicationConsent
from images.models import (
    AerialGeoreference,
    Collection,
    Comment,
    Georeference,
    GeoreferenceValidation,
    Image,
    License,
    Source,
    SubjectMapping,
)
from subjects.models import OsmElement, Subject, WikidataItem

POLYGON_COORDS = (
    (-77.44, 37.53),
    (-77.43, 37.53),
    (-77.43, 37.54),
    (-77.44, 37.54),
    (-77.44, 37.53),
)


class ApiFixturesMixin:
    """Shared test fixtures for all API endpoint tests."""

    @classmethod
    def setUpTestData(cls):
        # -- Users --
        cls.user_alice = User.objects.create_user(
            username="osm_100",
            first_name="Alice",
            password="test",
        )
        cls.user_bob = User.objects.create_user(
            username="osm_200",
            first_name="Bob",
            password="test",
        )
        cls.user_carol = User.objects.create_user(
            username="osm_300",
            first_name="Carol",
            password="test",
        )
        cls.user_validator = User.objects.create_user(
            username="osm_400",
            first_name="Dan",
            password="test",
        )

        # -- Sources --
        cls.source = Source.objects.create(
            name="Library of Virginia",
            slug="lva",
            url="https://example.com/lva",
            description="Public archive.",
            public=True,
        )
        cls.source_private = Source.objects.create(
            name="Private Archive",
            slug="private",
            url="https://example.com/priv",
            description="Not public.",
            public=False,
        )

        # -- Collections --
        cls.collection = Collection.objects.create(
            source=cls.source,
            name="Collection A",
            slug="a",
            url="https://example.com/a",
            public=True,
        )
        cls.collection_b = Collection.objects.create(
            source=cls.source,
            name="Collection B",
            slug="b",
            url="https://example.com/b",
            public=True,
        )
        cls.collection_private = Collection.objects.create(
            source=cls.source_private,
            name="Private",
            slug="priv",
            url="https://example.com/priv-coll",
            public=True,
        )

        # -- Images --
        # Set fuzzy date fields directly to avoid EDTF parsing complexity
        cls.img1 = Image.objects.create(
            collection=cls.collection,
            title="Main Street 1900",
            permalink="https://img.example.com/1.jpg",
            original_date="ca. 1900-1910",
        )
        Image.objects.filter(pk=cls.img1.pk).update(
            fuzzy_start_decdate=1900,
            fuzzy_end_decdate=1910,
        )
        cls.img2 = Image.objects.create(
            collection=cls.collection,
            title="Broad Street 1920",
            permalink="https://img.example.com/2.jpg",
            original_date="ca. 1920-1930",
        )
        Image.objects.filter(pk=cls.img2.pk).update(
            fuzzy_start_decdate=1920,
            fuzzy_end_decdate=1930,
        )
        cls.img3 = Image.objects.create(
            collection=cls.collection_b,
            title="Aerial of City 1940",
            permalink="https://img.example.com/3.jpg",
            original_date="ca. 1940",
            aerial=True,
        )
        Image.objects.filter(pk=cls.img3.pk).update(
            fuzzy_start_decdate=1940,
            fuzzy_end_decdate=1940,
        )
        cls.img_duplicate = Image.objects.create(
            collection=cls.collection,
            title="Main Street 1900 (duplicate)",
            permalink="https://img.example.com/dup.jpg",
            duplicate_of=cls.img1,
        )
        cls.img_private = Image.objects.create(
            collection=cls.collection_private,
            title="Private Image",
            permalink="https://img.example.com/4.jpg",
        )

        # Refresh to pick up signal-computed is_searchable
        for img in [cls.img1, cls.img2, cls.img3, cls.img_duplicate, cls.img_private]:
            img.refresh_from_db()

        # -- Subject + mapping --
        cls.wikidata_item = WikidataItem.objects.create(
            wikidata_id="Q1",
            title="Main Street",
        )
        cls.subject = Subject.objects.create(
            title="Main Street",
            slug="main-street",
            wikidata_item=cls.wikidata_item,
        )
        SubjectMapping.objects.create(image=cls.img1, subject=cls.subject)
        cls.osm_element = OsmElement.objects.create(
            osm_id=12345,
            subject=cls.subject,
            geometry=Polygon(POLYGON_COORDS, srid=4326),
        )

        # -- Georeferences --
        cls.georef1 = Georeference.objects.create(
            image=cls.img1,
            point=Point(-77.43, 37.54, srid=4326),
            confidence="high",
            georeferenced_by=cls.user_alice,
        )
        cls.georef2_old = Georeference.objects.create(
            image=cls.img2,
            point=Point(-77.44, 37.53, srid=4326),
            confidence="medium",
            georeferenced_by=cls.user_alice,
        )
        # Backdate so georef2_new wins the "most recent per image" deduplication
        Georeference.objects.filter(pk=cls.georef2_old.pk).update(
            georeferenced_at=timezone.now() - timedelta(days=1),
        )
        cls.georef2_old.refresh_from_db()

        cls.georef2_new = Georeference.objects.create(
            image=cls.img2,
            point=Point(-77.45, 37.53, srid=4326),
            confidence="low",
            georeferenced_by=cls.user_alice,
        )

        # -- Aerial georeference --
        cls.aerial_georef = AerialGeoreference.objects.create(
            image=cls.img3,
            polygon=Polygon(POLYGON_COORDS, srid=4326),
            confidence="high",
            georeferenced_by=cls.user_bob,
        )

        # -- Validation --
        cls.validation = GeoreferenceValidation.objects.create(
            georeference=cls.georef1,
            validated_by=cls.user_validator,
            validation="correct",
        )

        # -- Comment --
        cls.comment = Comment.objects.create(
            image=cls.img1,
            text="Great photo!",
            commented_by=cls.user_bob,
        )

        # -- Activity objects (signals use on_commit, which doesn't fire
        #    in setUpTestData, so create manually) --
        now = timezone.now()
        cls.georef_group = GeoreferenceGroup.objects.create(
            user=cls.user_alice,
            started_at=cls.georef2_old.georeferenced_at,
            ended_at=cls.georef2_new.georeferenced_at,
            count=3,
        )
        GeoreferenceGroupMember.objects.create(
            group=cls.georef_group,
            georeference=cls.georef1,
            added_at=cls.georef1.georeferenced_at,
        )
        GeoreferenceGroupMember.objects.create(
            group=cls.georef_group,
            georeference=cls.georef2_new,
            added_at=cls.georef2_new.georeferenced_at,
        )
        cls.user_milestone = UserMilestone.objects.create(
            user=cls.user_alice,
            count=5,
            reached_at=now,
        )
        cls.sitewide_milestone = SitewideMilestone.objects.create(
            count=100,
            reached_at=now,
        )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class TestUsersEndpoint(ApiFixturesMixin, TestCase):
    def test_list_status(self):
        resp = self.client.get("/api/v2/users/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_user_without_georeferences_excluded(self):
        resp = self.client.get("/api/v2/users/")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertNotIn(300, ids)  # Carol has no georefs

    def test_detail_by_osm_id(self):
        resp = self.client.get("/api/v2/users/100/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], 100)
        self.assertEqual(data["username"], "Alice")

    def test_detail_404(self):
        resp = self.client.get("/api/v2/users/999/")
        self.assertEqual(resp.status_code, 404)

    def test_response_fields(self):
        resp = self.client.get("/api/v2/users/100/")
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("username", data)
        self.assertIn("point_georeferences", data)
        self.assertIn("from_above_georeferences", data)

    def test_ordering_by_username(self):
        resp = self.client.get("/api/v2/users/?ordering=username")
        results = resp.json()["results"]
        names = [r["username"] for r in results]
        self.assertEqual(names, sorted(names))

    def test_ordering_by_point_georeferences_desc(self):
        resp = self.client.get("/api/v2/users/?ordering=-point_georeferences")
        results = resp.json()["results"]
        counts = [r["point_georeferences"] for r in results]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_counts_no_cross_product_inflation(self):
        """User with both point and aerial georefs should not get inflated counts."""
        # Give Alice an aerial georeference (she already has 3 point georefs)
        AerialGeoreference.objects.create(
            image=self.img3,
            polygon=Polygon(POLYGON_COORDS, srid=4326),
            confidence="medium",
            georeferenced_by=self.user_alice,
        )
        resp = self.client.get("/api/v2/users/100/")
        data = resp.json()
        self.assertEqual(data["point_georeferences"], 3)
        self.assertEqual(data["from_above_georeferences"], 1)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class TestSourcesEndpoint(ApiFixturesMixin, TestCase):
    def test_list_status_and_count(self):
        resp = self.client.get("/api/v2/sources/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_private_source_excluded(self):
        resp = self.client.get("/api/v2/sources/")
        slugs = [r["slug"] for r in resp.json()["results"]]
        self.assertNotIn("private", slugs)

    def test_detail(self):
        resp = self.client.get(f"/api/v2/sources/{self.source.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "Library of Virginia")
        self.assertGreaterEqual(data["collection_count"], 1)
        self.assertGreaterEqual(data["image_count"], 1)

    def test_filter_by_slug(self):
        resp = self.client.get("/api/v2/sources/?slug=lva")
        self.assertEqual(resp.json()["count"], 1)

    def test_collections_url_present(self):
        resp = self.client.get(f"/api/v2/sources/{self.source.pk}/")
        self.assertIn("collections_url", resp.json())
        self.assertIn(
            f"/api/v2/sources/{self.source.pk}/collections/",
            resp.json()["collections_url"],
        )


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


class TestCollectionsEndpoint(ApiFixturesMixin, TestCase):
    def test_list_status_and_count(self):
        resp = self.client.get("/api/v2/collections/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_private_collection_excluded(self):
        resp = self.client.get("/api/v2/collections/")
        slugs = [r["slug"] for r in resp.json()["results"]]
        self.assertNotIn("priv", slugs)

    def test_detail(self):
        resp = self.client.get(f"/api/v2/collections/{self.collection.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("source", data)
        self.assertEqual(data["source"]["id"], self.source.pk)
        self.assertEqual(data["image_count"], 2)

    def test_filter_by_source(self):
        resp = self.client.get(f"/api/v2/collections/?source={self.source.pk}")
        self.assertEqual(resp.json()["count"], 2)

    def test_filter_by_slug(self):
        resp = self.client.get("/api/v2/collections/?slug=a")
        self.assertEqual(resp.json()["count"], 1)

    def test_nested_route(self):
        resp = self.client.get(f"/api/v2/sources/{self.source.pk}/collections/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_create_with_blank_url(self):
        staff = User.objects.create_user(
            username="osm_500",
            first_name="Eve",
            password="test",
            is_staff=True,
        )
        self.client.force_login(staff)
        resp = self.client.post(
            "/api/v2/collections/",
            {
                "name": "No URL Collection",
                "slug": "no-url",
                "source": self.source.pk,
                "url": "",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["url"], "")


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


class TestImagesEndpoint(ApiFixturesMixin, TestCase):
    def test_list_status_and_count(self):
        resp = self.client.get("/api/v2/images/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 4)

    def test_private_image_excluded(self):
        resp = self.client.get("/api/v2/images/")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertNotIn(self.img_private.pk, ids)

    def test_list_uses_list_serializer(self):
        """List response should not include heavy detail fields."""
        resp = self.client.get("/api/v2/images/")
        first = resp.json()["results"][0]
        self.assertNotIn("georeferences", first)
        self.assertNotIn("subjects", first)
        self.assertIn("georeference_status", first)

    def test_detail_includes_georeferences(self):
        resp = self.client.get(f"/api/v2/images/{self.img1.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("georeferences", data)
        self.assertEqual(len(data["georeferences"]), 1)
        georef = data["georeferences"][0]
        self.assertEqual(georef["confidence"], "high")
        self.assertIn("latitude", georef)
        self.assertIn("longitude", georef)

    def test_detail_includes_subjects(self):
        resp = self.client.get(f"/api/v2/images/{self.img1.pk}/")
        subjects = resp.json()["subjects"]
        self.assertEqual(len(subjects), 1)
        self.assertEqual(subjects[0]["title"], "Main Street")

    def test_detail_includes_comments(self):
        resp = self.client.get(f"/api/v2/images/{self.img1.pk}/")
        comments = resp.json()["comments"]
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["text"], "Great photo!")

    def test_detail_includes_validations(self):
        resp = self.client.get(f"/api/v2/images/{self.img1.pk}/")
        georef = resp.json()["georeferences"][0]
        self.assertEqual(len(georef["validations"]), 1)
        self.assertEqual(georef["validations"][0]["validation"], "correct")

    def test_detail_404(self):
        resp = self.client.get("/api/v2/images/99999/")
        self.assertEqual(resp.status_code, 404)

    def test_filter_by_collection(self):
        resp = self.client.get(f"/api/v2/images/?collection={self.collection.pk}")
        self.assertEqual(resp.json()["count"], 3)

    def test_filter_by_subject(self):
        resp = self.client.get(f"/api/v2/images/?subject={self.subject.pk}")
        self.assertEqual(resp.json()["count"], 1)

    def test_filter_by_year_min(self):
        # year_min=1915: includes images whose fuzzy_end_decdate >= 1915
        # img1 ends ~1910 → excluded; img2 ends ~1930 → included; img3 ~1940 → included
        resp = self.client.get("/api/v2/images/?year_min=1915")
        self.assertEqual(resp.json()["count"], 2)

    def test_filter_by_year_max(self):
        # year_max=1915: includes images whose fuzzy_start_decdate <= 1915
        # img1 starts ~1900 → included; img2 starts ~1920 → excluded; img3 ~1940 → excluded
        resp = self.client.get("/api/v2/images/?year_max=1915")
        self.assertEqual(resp.json()["count"], 1)

    def test_filter_georeferenced_true(self):
        """Includes non-aerial images with point georefs and aerial images with polygon georefs."""
        resp = self.client.get("/api/v2/images/?georeferenced=true")
        ids = [r["id"] for r in resp.json()["results"]]
        # Non-aerial with point georeferences
        self.assertIn(self.img1.pk, ids)
        self.assertIn(self.img2.pk, ids)
        # Aerial with polygon georeference
        self.assertIn(self.img3.pk, ids)
        # Duplicate has no georeferences
        self.assertNotIn(self.img_duplicate.pk, ids)

    def test_filter_georeferenced_false(self):
        """Excludes both point-georeferenced and aerial-georeferenced images."""
        resp = self.client.get("/api/v2/images/?georeferenced=false")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertIn(self.img_duplicate.pk, ids)
        self.assertNotIn(self.img1.pk, ids)
        self.assertNotIn(self.img3.pk, ids)

    def test_filter_georeferenced_ignores_polygon_on_non_aerial(self):
        """A non-aerial image with only a polygon georef is not considered georeferenced."""
        # Make img3 non-aerial; it still has an AerialGeoreference but no point georef
        Image.objects.filter(pk=self.img3.pk).update(aerial=False)
        resp = self.client.get("/api/v2/images/?georeferenced=true")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertNotIn(self.img3.pk, ids)

    def test_filter_georeferenced_ignores_point_on_aerial(self):
        """An aerial image with only a point georef is not considered georeferenced."""
        # Make img1 aerial; it has point georefs but no AerialGeoreference
        Image.objects.filter(pk=self.img1.pk).update(aerial=True)
        resp = self.client.get("/api/v2/images/?georeferenced=true")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertNotIn(self.img1.pk, ids)

    def test_filter_from_above(self):
        resp = self.client.get("/api/v2/images/?from_above=true")
        self.assertEqual(resp.json()["count"], 1)
        self.assertEqual(resp.json()["results"][0]["id"], self.img3.pk)

    def test_ordering_default(self):
        """Default ordering is -order (highest id first)."""
        resp = self.client.get("/api/v2/images/")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_ordering_by_title(self):
        resp = self.client.get("/api/v2/images/?ordering=title")
        titles = [r["title"] for r in resp.json()["results"]]
        self.assertEqual(titles, sorted(titles))

    def test_duplicate_included_in_list(self):
        resp = self.client.get("/api/v2/images/")
        ids = [r["id"] for r in resp.json()["results"]]
        self.assertIn(self.img_duplicate.pk, ids)

    def test_duplicate_of_field_in_list(self):
        resp = self.client.get("/api/v2/images/")
        by_id = {r["id"]: r for r in resp.json()["results"]}
        self.assertEqual(by_id[self.img_duplicate.pk]["duplicate_of"], self.img1.pk)
        self.assertIsNone(by_id[self.img1.pk]["duplicate_of"])

    def test_duplicate_detail_accessible(self):
        resp = self.client.get(f"/api/v2/images/{self.img_duplicate.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["duplicate_of"], self.img1.pk)

    def test_non_duplicate_detail_has_null_duplicate_of(self):
        resp = self.client.get(f"/api/v2/images/{self.img1.pk}/")
        self.assertIsNone(resp.json()["duplicate_of"])


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


class TestSubjectsEndpoint(ApiFixturesMixin, TestCase):
    def test_list_status_and_count(self):
        resp = self.client.get("/api/v2/subjects/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_detail(self):
        resp = self.client.get(f"/api/v2/subjects/{self.subject.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["title"], "Main Street")
        self.assertEqual(data["image_count"], 1)
        self.assertIn("images_url", data)

    def test_filter_by_slug(self):
        resp = self.client.get("/api/v2/subjects/?slug=main-street")
        self.assertEqual(resp.json()["count"], 1)

    def test_geometry_action(self):
        resp = self.client.get(f"/api/v2/subjects/{self.subject.pk}/geometry/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(len(data["features"]), 1)
        feature = data["features"][0]
        self.assertEqual(feature["properties"]["osm_id"], 12345)

    def test_geometry_empty_subject(self):
        """Geometry endpoint returns empty FeatureCollection for subject with no OSM elements."""
        # Create a subject with an image mapping but no OsmElements
        wd2 = WikidataItem.objects.create(
            wikidata_id="Q2",
            title="Empty Subject",
        )
        subj2 = Subject.objects.create(
            title="Empty Subject",
            slug="empty",
            wikidata_item=wd2,
        )
        SubjectMapping.objects.create(image=self.img2, subject=subj2)
        resp = self.client.get(f"/api/v2/subjects/{subj2.pk}/geometry/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["features"], [])

    def test_geometry_nonexistent_subject(self):
        """Geometry endpoint returns 404 for a subject that does not exist."""
        resp = self.client.get("/api/v2/subjects/999999/geometry/")
        self.assertEqual(resp.status_code, 404)


# ---------------------------------------------------------------------------
# Licenses
# ---------------------------------------------------------------------------


class TestLicensesEndpoint(TestCase):
    # Note: a data migration seeds Flickr's 17 default licenses, so tests
    # assert against named fixtures rather than exact counts.

    @classmethod
    def setUpTestData(cls):
        cls.test_a = License.objects.create(
            name="Test License A",
            display_name="Test License A (display)",
            permalink="https://example.com/a",
        )
        cls.test_b = License.objects.create(
            name="Test License B",
            display_name="Test License B (display)",
        )

    def test_list_status(self):
        resp = self.client.get("/api/v2/licenses/")
        self.assertEqual(resp.status_code, 200)

    def test_list_is_unpaginated(self):
        """The endpoint returns a plain list, not a paginated envelope."""
        resp = self.client.get("/api/v2/licenses/")
        body = resp.json()
        self.assertIsInstance(body, list)
        names = [item["name"] for item in body]
        self.assertIn("Test License A", names)
        self.assertIn("Test License B", names)

    def test_response_fields(self):
        resp = self.client.get("/api/v2/licenses/")
        by_name = {item["name"]: item for item in resp.json()}
        item = by_name["Test License A"]
        self.assertEqual(item["display_name"], "Test License A (display)")
        self.assertEqual(item["permalink"], "https://example.com/a")

    def test_ordering_by_name(self):
        resp = self.client.get("/api/v2/licenses/")
        names = [item["name"] for item in resp.json()]
        self.assertEqual(names, sorted(names))

    def test_detail(self):
        resp = self.client.get(f"/api/v2/licenses/{self.test_a.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Test License A")


# ---------------------------------------------------------------------------
# Georeferences (GeoJSON)
# ---------------------------------------------------------------------------


class TestGeoreferencesEndpoint(ApiFixturesMixin, TestCase):
    def test_list_geojson_shape(self):
        resp = self.client.get("/api/v2/georeferences/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertIn("count", data)
        self.assertIn("features", data)

    def test_most_recent_per_image(self):
        """Only the most recent georeference per image should appear."""
        resp = self.client.get("/api/v2/georeferences/")
        data = resp.json()
        # img1 has 1 georef, img2 has 2 but only the newest should appear
        self.assertEqual(data["count"], 2)
        # GeoJSON: id is at the feature level, not inside properties
        feature_ids = [f["id"] for f in data["features"]]
        self.assertIn(self.georef1.pk, feature_ids)
        self.assertIn(self.georef2_new.pk, feature_ids)
        self.assertNotIn(self.georef2_old.pk, feature_ids)

    def test_validation_count(self):
        resp = self.client.get("/api/v2/georeferences/")
        features = resp.json()["features"]
        by_id = {f["id"]: f for f in features}
        self.assertEqual(by_id[self.georef1.pk]["properties"]["validation_count"], 1)
        self.assertEqual(
            by_id[self.georef2_new.pk]["properties"]["validation_count"], 0
        )

    def test_feature_properties(self):
        resp = self.client.get("/api/v2/georeferences/")
        feature = resp.json()["features"][0]
        self.assertIn("id", feature)
        props = feature["properties"]
        for key in [
            "image_id",
            "image_title",
            "direction",
            "confidence",
            "georeferenced_by",
            "georeferenced_at",
            "validation_count",
        ]:
            self.assertIn(key, props)

    def test_filter_by_image(self):
        resp = self.client.get(f"/api/v2/georeferences/?image={self.img1.pk}")
        self.assertEqual(resp.json()["count"], 1)

    def test_filter_by_confidence(self):
        resp = self.client.get("/api/v2/georeferences/?confidence=high")
        self.assertEqual(resp.json()["count"], 1)
        self.assertEqual(
            resp.json()["features"][0]["id"],
            self.georef1.pk,
        )

    def test_filter_by_georeferenced_by(self):
        resp = self.client.get("/api/v2/georeferences/?georeferenced_by=100")
        self.assertEqual(resp.json()["count"], 2)

    def test_filter_by_year_min(self):
        # year_min=1915 excludes img1 (ends ~1910)
        resp = self.client.get("/api/v2/georeferences/?year_min=1915")
        self.assertEqual(resp.json()["count"], 1)

    def test_bbox_filter_includes(self):
        # Box covering all test points
        resp = self.client.get(
            "/api/v2/georeferences/?in_bbox=-77.46,37.52,-77.42,37.55"
        )
        self.assertGreaterEqual(resp.json()["count"], 1)

    def test_bbox_filter_excludes(self):
        # Box far from all test points
        resp = self.client.get("/api/v2/georeferences/?in_bbox=-78.0,38.0,-77.9,38.1")
        self.assertEqual(resp.json()["count"], 0)

    def test_ordering_by_validation_count(self):
        resp = self.client.get("/api/v2/georeferences/?ordering=-validation_count")
        features = resp.json()["features"]
        counts = [f["properties"]["validation_count"] for f in features]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_pagination(self):
        resp = self.client.get("/api/v2/georeferences/?page_size=1")
        data = resp.json()
        self.assertEqual(len(data["features"]), 1)
        self.assertIsNotNone(data["next"])
        self.assertEqual(data["count"], 2)


# ---------------------------------------------------------------------------
# From-above georeferences (GeoJSON)
# ---------------------------------------------------------------------------


class TestFromAboveGeoreferencesEndpoint(ApiFixturesMixin, TestCase):
    def test_list_geojson_shape(self):
        resp = self.client.get("/api/v2/from-above-georeferences/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(data["count"], 1)

    def test_feature_properties(self):
        resp = self.client.get("/api/v2/from-above-georeferences/")
        props = resp.json()["features"][0]["properties"]
        self.assertEqual(props["image_id"], self.img3.pk)
        self.assertEqual(props["confidence"], "high")
        self.assertEqual(props["georeferenced_by"], "Bob")
        self.assertEqual(props["validation_count"], 0)

    def test_filter_by_confidence(self):
        resp = self.client.get("/api/v2/from-above-georeferences/?confidence=high")
        self.assertEqual(resp.json()["count"], 1)

    def test_ordering(self):
        resp = self.client.get(
            "/api/v2/from-above-georeferences/?ordering=-georeferenced_at"
        )
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestStatsEndpoint(ApiFixturesMixin, TestCase):
    def test_status_and_shape(self):
        resp = self.client.get("/api/v2/stats/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in [
            "total_sources",
            "total_collections",
            "total_images",
            "georeferenced_images",
            "total_georeferences",
            "confidence_breakdown",
        ]:
            self.assertIn(key, data)

    def test_source_and_collection_counts(self):
        resp = self.client.get("/api/v2/stats/")
        data = resp.json()
        self.assertEqual(data["total_sources"], 1)
        self.assertEqual(data["total_collections"], 2)

    def test_confidence_breakdown(self):
        resp = self.client.get("/api/v2/stats/")
        breakdown = resp.json()["confidence_breakdown"]
        for key in ["low", "medium", "high"]:
            self.assertIn(key, breakdown)
            self.assertIsInstance(breakdown[key], int)
            self.assertGreaterEqual(breakdown[key], 0)


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


class TestActivityEndpoint(ApiFixturesMixin, TestCase):
    def test_status_and_shape(self):
        resp = self.client.get("/api/v2/activity/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_contains_georeference_group(self):
        resp = self.client.get("/api/v2/activity/")
        types = [e["type"] for e in resp.json()]
        self.assertIn("georeference_group", types)

    def test_georeference_group_data_shape(self):
        resp = self.client.get("/api/v2/activity/?types=georeference_group")
        events = resp.json()
        self.assertGreater(len(events), 0)
        event = events[0]
        self.assertEqual(event["type"], "georeference_group")
        self.assertIn("timestamp", event)
        data = event["data"]
        for key in ["user", "count", "started_at", "ended_at", "images"]:
            self.assertIn(key, data)

    def test_type_filtering(self):
        resp = self.client.get("/api/v2/activity/?types=comment")
        for event in resp.json():
            self.assertEqual(event["type"], "comment")

    def test_type_filtering_invalid(self):
        resp = self.client.get("/api/v2/activity/?types=nonexistent")
        self.assertEqual(resp.json(), [])

    def test_limit_param(self):
        resp = self.client.get("/api/v2/activity/?limit=1")
        self.assertLessEqual(len(resp.json()), 1)

    def test_before_param_old_date(self):
        resp = self.client.get("/api/v2/activity/?before=2000-01-01T00:00:00Z")
        self.assertEqual(resp.json(), [])

    def test_before_param_invalid(self):
        resp = self.client.get("/api/v2/activity/?before=not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearchEndpoints(ApiFixturesMixin, TestCase):
    # -- Semantic search --

    def test_semantic_search_missing_query(self):
        resp = self.client.get("/api/v2/search/semantic/")
        self.assertEqual(resp.status_code, 400)

    def test_semantic_search_query_too_long(self):
        resp = self.client.get(f"/api/v2/search/semantic/?q={'x' * 501}")
        self.assertEqual(resp.status_code, 400)

    # -- Text search --

    @patch("api.views.HAS_POSTGRES_SEARCH", False)
    def test_text_search_unavailable(self):
        resp = self.client.get("/api/v2/search/text/?q=test")
        self.assertEqual(resp.status_code, 503)

    @patch("api.views.HAS_POSTGRES_SEARCH", True)
    def test_text_search_missing_query(self):
        resp = self.client.get("/api/v2/search/text/")
        self.assertEqual(resp.status_code, 400)

    @patch("api.views.HAS_POSTGRES_SEARCH", True)
    def test_text_search_query_too_long(self):
        resp = self.client.get(f"/api/v2/search/text/?q={'x' * 501}")
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# OAuth authorization: remembered consent
# ---------------------------------------------------------------------------

OAUTH_REDIRECT_URI = "http://127.0.0.1/callback"


class OAuthConsentFixturesMixin:
    """Shared fixtures for the OAuth authorization and consent tests."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="osm_700", password="test")
        cls.other_user = User.objects.create_user(username="osm_800", password="test")
        cls.application = Application.objects.create(
            name="Desktop Importer",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=OAUTH_REDIRECT_URI,
        )
        verifier = "a" * 64
        cls.code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )

    def authorize_params(self, scope="read", **extra):
        params = {
            "response_type": "code",
            "client_id": self.application.client_id,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": scope,
            "state": "opaque",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
        }
        params.update(extra)
        return params

    def get_authorize(self, **extra):
        return self.client.get("/oauth/authorize/", self.authorize_params(**extra))

    def post_authorize(self, allow=True, scope="read"):
        data = self.authorize_params(scope=scope)
        if allow:
            data["allow"] = "on"
        return self.client.post("/oauth/authorize/", data)

    def create_consent(self, user=None, scope="read"):
        return ApplicationConsent.objects.create(
            user=user or self.user, application=self.application, scope=scope
        )


class TestOAuthRememberedConsent(OAuthConsentFixturesMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_first_authorization_shows_consent_form(self):
        resp = self.get_authorize()
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "oauth2_provider/authorize.html")

    def test_approval_issues_code_and_records_consent(self):
        resp = self.post_authorize()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(OAUTH_REDIRECT_URI))
        self.assertIn("code=", resp["Location"])
        consent = ApplicationConsent.objects.get(
            user=self.user, application=self.application
        )
        self.assertEqual(consent.scope, "read")

    def test_denial_records_no_consent(self):
        resp = self.post_authorize(allow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("error=access_denied", resp["Location"])
        self.assertFalse(ApplicationConsent.objects.exists())

    def test_remembered_consent_skips_form(self):
        self.create_consent()
        # No access or refresh tokens exist: the skip must come from the
        # consent record alone, so it survives token expiry and revocation.
        self.assertFalse(AccessToken.objects.exists())
        resp = self.get_authorize()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(OAUTH_REDIRECT_URI))
        self.assertIn("code=", resp["Location"])
        self.assertIn("state=opaque", resp["Location"])

    def test_narrower_scope_still_skips(self):
        self.create_consent(scope="read import")
        resp = self.get_authorize(scope="read")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("code=", resp["Location"])

    def test_scope_escalation_reprompts(self):
        self.create_consent(scope="read")
        resp = self.get_authorize(scope="read import")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "oauth2_provider/authorize.html")

    def test_approving_new_scope_merges_grant(self):
        self.create_consent(scope="read")
        resp = self.post_authorize(scope="read import")
        self.assertEqual(resp.status_code, 302)
        consent = ApplicationConsent.objects.get(
            user=self.user, application=self.application
        )
        self.assertEqual(consent.scope, "import read")

    def test_consent_is_per_user(self):
        self.create_consent(user=self.other_user)
        resp = self.get_authorize()
        self.assertEqual(resp.status_code, 200)

    def test_consent_is_per_application(self):
        other_app = Application.objects.create(
            name="Impostor",
            client_type=Application.CLIENT_PUBLIC,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris=OAUTH_REDIRECT_URI,
        )
        ApplicationConsent.objects.create(
            user=self.user, application=other_app, scope="read"
        )
        resp = self.get_authorize()
        self.assertEqual(resp.status_code, 200)

    def test_approval_prompt_force_reprompts(self):
        self.create_consent()
        resp = self.get_authorize(approval_prompt="force")
        self.assertEqual(resp.status_code, 200)

    def test_non_s256_rejected(self):
        resp = self.client.get(
            "/oauth/authorize/",
            self.authorize_params(code_challenge_method="plain"),
        )
        self.assertEqual(resp.status_code, 400)


class TestAuthorizedApplicationsSettings(OAuthConsentFixturesMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def create_tokens(self):
        access = AccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="access-token-1",
            expires=timezone.now() + timedelta(hours=8),
            scope="read",
        )
        refresh = RefreshToken.objects.create(
            user=self.user,
            application=self.application,
            token="refresh-token-1",
            access_token=access,
        )
        return access, refresh

    def test_list_shows_consented_application(self):
        self.create_consent()
        resp = self.client.get("/settings/oauth/authorized_tokens/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Desktop Importer")

    def test_list_requires_login(self):
        self.client.logout()
        resp = self.client.get("/settings/oauth/authorized_tokens/")
        self.assertEqual(resp.status_code, 302)

    def test_revoke_deletes_consent_and_tokens(self):
        consent = self.create_consent()
        access, refresh = self.create_tokens()
        resp = self.client.post(
            f"/settings/oauth/authorized_tokens/{consent.pk}/delete/"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ApplicationConsent.objects.filter(pk=consent.pk).exists())
        self.assertFalse(AccessToken.objects.filter(pk=access.pk).exists())
        refresh.refresh_from_db()
        self.assertIsNotNone(refresh.revoked)
        # The next authorization request shows the consent form again.
        resp = self.get_authorize()
        self.assertEqual(resp.status_code, 200)

    def test_cannot_revoke_other_users_consent(self):
        consent = self.create_consent(user=self.other_user)
        resp = self.client.post(
            f"/settings/oauth/authorized_tokens/{consent.pk}/delete/"
        )
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(ApplicationConsent.objects.filter(pk=consent.pk).exists())


# ---------------------------------------------------------------------------
# RSS Feeds
# ---------------------------------------------------------------------------


class TestSitewideActivityFeed(ApiFixturesMixin, TestCase):
    def test_feed_status_and_type(self):
        resp = self.client.get("/activity/feed/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/rss+xml; charset=utf-8")

    def test_feed_content(self):
        resp = self.client.get("/activity/feed/")
        content = resp.content.decode("utf-8")
        
        self.assertIn('<rss version="2.0"', content)
        self.assertIn("<title>Yesterdays - Site-wide Activity</title>", content)
        # Based on the test fixtures, we should have a milestone in the activity feed
        self.assertIn("milestone", content.lower())


class TestSubjectActivityFeed(ApiFixturesMixin, TestCase):
    def test_feed_status_and_type(self):
        resp = self.client.get(f"/subjects/{self.subject.slug}/feed/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/rss+xml; charset=utf-8")

    def test_feed_content(self):
        resp = self.client.get(f"/subjects/{self.subject.slug}/feed/")
        content = resp.content.decode("utf-8")
        self.assertIn('<rss version="2.0"', content)
        self.assertIn(self.img1.title, content)

    def test_feed_404(self):
        resp = self.client.get("/subjects/fake-subject/feed/")
        self.assertEqual(resp.status_code, 404)
