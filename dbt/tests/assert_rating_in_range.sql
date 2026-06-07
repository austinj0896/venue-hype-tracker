select
    google_place_id,
    rating
from {{ ref('dim_places') }}
where rating is not null
  and (rating < 0 or rating > 5)
