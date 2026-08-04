"""Trigram GIN index on ``Subject.title``.

Backs the subject-tagging autocomplete, which matches ``title__icontains``
OR ``word_similarity(query, title) >= threshold``. The index accelerates
only the ``ILIKE '%q%'`` branch that ``__icontains`` compiles to; the
``WORD_SIMILARITY(...)`` annotation is a plain function call computed per
row (pg_trgm's index support for word similarity is the ``%>``/``<%``
operators, which the ORM function form does not emit), and the OR likely
forces a sequential scan for the combined query anyway. That is fine at
the subjects table's current size; if it ever grows large, the raw ``%>``
idiom used by the image text search (``images/views/search.py``) is the
escape hatch.

The ``pg_trgm`` extension itself is already created by
``images.migrations.0035_enhance_search_vector``, which this app depends
on transitively via ``0014_wikidataitem_title_trgm``; no need to enable it
again here.
"""

from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("subjects", "0017_remove_subject_description"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="subject",
            index=GinIndex(
                fields=["title"],
                name="subject_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
