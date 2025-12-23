from .album import (
    add_image_to_album,
    album_detail,
    bulk_add_to_album,
    bulk_create_and_add_to_album,
    create_and_add_to_album,
    delete_album,
    edit_album,
    remove_image_from_album,
    toggle_album_public,
    user_albums_api,
)
from .api import (
    aerial_geojson_endpoint,
    geojson_endpoint,
    map_layers_view,
    osm_elements_vector_tiles_endpoint,
    polygonal_georeferences_at_point,
    vector_tiles_endpoint,
)
from .browse import (
    browse_aerials,
    browse_sources,
    browse_subjects,
    collection_detail,
    image_detail,
    image_list,
    source_detail,
    subject_detail,
    top_rated_images,
)
from .core import (
    add_comment,
    get_min_scale_for_zoom,
    get_random_image,
    image_stats,
    label_scales,
    map_embed,
    mark_aerial,
    mark_difficulty,
    mark_scale,
    mark_will_not_georef,
    skip_image,
    submit_rating,
    update_image_scale,
)
from .georeference import (
    aerial_georeference_image,
    aerial_georeference_interface,
    georeference_image,
    georeference_interface,
    validate_georeference,
)
from .search import (
    find_similar_images,
    reverse_image_search,
    search_page,
    semantic_search,
    text_search,
)
from .subject import (
    add_subject_to_image,
    all_subjects_api,
    bulk_add_subject_to_images,
    find_similar_images_to_subject,
    remove_subject_from_image,
    reorder_subjects,
    subject_autocomplete,
)
