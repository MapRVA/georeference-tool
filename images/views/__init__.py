from .core import (
    get_min_scale_for_zoom,
    map_embed,
    image_stats,
    get_random_image,
    add_comment,
    submit_rating,
    skip_image,
    mark_difficulty,
    mark_scale,
    mark_will_not_georef,
    mark_aerial,
    update_image_scale,
)

from .browse import (
    browse_aerials,
    browse_sources,
    browse_subjects,
    collection_detail,
    source_detail,
    subject_detail,
    top_rated_images,
    image_list,
    image_detail,
)

from .georeference import (
    georeference_interface,
    georeference_image,
    aerial_georeference_interface,
    aerial_georeference_image,
    validate_georeference,
    label_scales,
)

from .search import search_page, semantic_search, text_search, find_similar_images

from .api import (
    geojson_endpoint,
    aerial_geojson_endpoint,
    polygonal_georeferences_at_point,
    vector_tiles_endpoint,
    osm_elements_vector_tiles_endpoint,
    map_layers_view,
)

from .album import (
    edit_album,
    delete_album,
    user_albums_api,
    add_image_to_album,
    create_and_add_to_album,
    remove_image_from_album,
    album_detail,
    toggle_album_public,
    bulk_add_to_album,
    bulk_create_and_add_to_album,
)

from .subject import (
    subject_autocomplete,
    all_subjects_api,
    add_subject_to_image,
    bulk_add_subject_to_images,
    remove_subject_from_image,
    reorder_subjects,
    find_similar_images_to_subject,
)
