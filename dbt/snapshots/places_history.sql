{% snapshot places_history %}

{{
    config(
      target_schema='SNAPSHOTS',
      unique_key='google_place_id',
      strategy='timestamp',
      updated_at='loaded_at',
    )
}}

select
    google_place_id,
    place_name,
    primary_type,
    venue_category,
    rating,
    user_rating_count,
    business_status,
    latitude,
    longitude,
    borough,
    first_seen_at,
    last_seen_at,
    loaded_at
from {{ ref('dim_places') }}

{% endsnapshot %}
