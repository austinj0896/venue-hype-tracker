-- Fails if the mart has no rows (e.g. fetch never ran).
select 1 as failure
where (select count(*) from {{ ref('dim_places') }}) = 0
