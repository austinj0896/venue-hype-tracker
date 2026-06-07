select
    google_place_id,
    user_rating_count
from {{ ref('dim_places') }}
where user_rating_count is not null
  and user_rating_count < 0
