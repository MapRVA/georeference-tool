from django.db import models, transaction


class Region(models.Model):
    """Admin-curated geographic region backed by a Wikidata entity.

    Sources, collections, and images reference regions via nullable FKs;
    an image's effective region resolves image -> collection -> source
    (``Image.effective_region``). Regions are created only through the
    Django admin, which verifies the Wikidata item's class membership
    (see ``regions.wikidata_check``) before saving.
    """

    title = models.CharField(max_length=500, help_text="Name of the region")
    slug = models.SlugField(unique=True)
    wikidata_item = models.OneToOneField(
        "subjects.WikidataItem",
        on_delete=models.CASCADE,
        related_name="region",
        help_text="Linked Wikidata item",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        old_item_id = None
        if self.pk:
            old_item_id = (
                Region.objects.filter(pk=self.pk)
                .values_list("wikidata_item_id", flat=True)
                .first()
            )
        if not self.title and self.wikidata_item_id:
            self.title = self.wikidata_item.title
        super().save(*args, **kwargs)

        # An already-hydrated item (previously a Subject or a closure
        # ancestor) was mirrored without the P131 containment chain, so
        # attaching a Region to it needs a closure re-pull. A never-
        # hydrated item is skipped: its own save() already queued
        # hydration, which runs post-commit and therefore sees this row.
        if (
            self.wikidata_item_id != old_item_id
            and self.wikidata_item.sparql_last_loaded_at is not None
        ):
            # Imported here, not at module level: subjects.tasks imports
            # this module (same cycle WikidataItem.save() dodges).
            from subjects.tasks import hydrate_wikidata_item

            qid = self.wikidata_item.wikidata_id
            transaction.on_commit(lambda: hydrate_wikidata_item.delay(qid))


class RegionAncestor(models.Model):
    """Materialized ``Region -> WikidataItem`` containment relation.

    A flat projection of each Region's transitive P131 (located in the
    administrative territorial entity) ancestors, refreshed from the
    Memgraph mirror after each closure load. Unlike ``SubjectAncestor``
    (which deliberately folds is-a and part-of together for category
    browse), this holds only administrative containment, so "regions
    transitively inside X" stays answerable as an indexed SQL query.
    """

    region = models.ForeignKey(
        "Region",
        on_delete=models.CASCADE,
        related_name="ancestors",
    )
    ancestor = models.ForeignKey(
        "subjects.WikidataItem",
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["region", "ancestor"],
                name="regionancestor_unique_pair",
            ),
        ]
        indexes = [
            models.Index(fields=["ancestor"]),
        ]

    def __str__(self):
        return f"{self.region} -> {self.ancestor}"
