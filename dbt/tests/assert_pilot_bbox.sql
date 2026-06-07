-- Geography guardrail for the active pilot area (see pilot_bbox_* vars in dbt_project.yml).
select
    google_place_id,
    latitude,
    longitude
from {{ ref('dim_places') }}
where latitude is not null
  and longitude is not null
  and (
    latitude < {{ var('pilot_bbox_south') }}
    or latitude > {{ var('pilot_bbox_north') }}
    or longitude < {{ var('pilot_bbox_west') }}
    or longitude > {{ var('pilot_bbox_east') }}
  )
