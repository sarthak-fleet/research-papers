-- SQL UDFs that correct OpenAlex's metadata bugs at query time.
-- arxiv_id is authoritative for submission date (YYMM prefix); OpenAlex
-- sometimes returns the revision date which can be years off.

CREATE OR REPLACE FUNCTION effective_year AS (source, arxiv_id, submitted_date) ->
  if(source = 'arxiv' AND length(arxiv_id) >= 7 AND match(arxiv_id, '^[0-9]{4}\.[0-9]+$'),
     2000 + toUInt16(substring(arxiv_id, 1, 2)),
     toYear(submitted_date));

CREATE OR REPLACE FUNCTION effective_date AS (source, arxiv_id, submitted_date) ->
  if(source = 'arxiv' AND length(arxiv_id) >= 7 AND match(arxiv_id, '^[0-9]{4}\.[0-9]+$'),
     makeDate(2000 + toUInt16(substring(arxiv_id, 1, 2)),
              greatest(1, toUInt8(substring(arxiv_id, 3, 2))), 1),
     submitted_date);
