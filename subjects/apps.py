from django.apps import AppConfig


class SubjectsConfig(AppConfig):
    name = "subjects"

    def ready(self):
        # Importing this module wires up the post_save / post_delete
        # signals that keep the Oxigraph project graph in sync with the
        # Subject table.
        from . import project_graph  # noqa: F401
