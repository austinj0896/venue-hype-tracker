with source as (
    select * from {{ source('venue_hype_raw', 'places') }}
),

renamed as (
    select
        place_key,
        google_place_id,
        name as place_name,
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
        source as ingest_source,
        first_seen_at,
        last_seen_at,
        loaded_at
    from source
)

select * from renamed
