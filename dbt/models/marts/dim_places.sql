select
    place_key,
    google_place_id,
    place_name,
    formatted_address,
    short_formatted_address,
    latitude,
    longitude,
    primary_type,
    types,
    business_status,
    rating,
    user_rating_count,
    price_level,
    website_uri,
    borough,
    ingest_source,
    first_seen_at,
    last_seen_at,
    loaded_at,
    case
        when primary_type in ('bar', 'night_club', 'pub', 'wine_bar', 'cocktail_bar', 'sports_bar')
            then 'nightlife'
        when primary_type in ('restaurant', 'cafe', 'bakery', 'coffee_shop')
            then 'food_drink'
        when primary_type in ('event_venue', 'concert_hall', 'banquet_hall', 'live_music_venue')
            then 'events'
        else 'other'
    end as venue_category
from {{ ref('stg_places') }}
