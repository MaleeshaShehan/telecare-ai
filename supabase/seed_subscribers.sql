-- Synthetic development subscribers for TeleCare AI.
-- Safe to rerun: subscriber_id is used as the upsert key.
--
-- The phone numbers are intentionally non-customer development data. They will
-- not receive real SMS messages. Add a separate row containing a phone number
-- you control when testing the complete Textit OTP flow.

with synthetic_subscribers as (
    select
        series_number,
        'SUB-' || lpad(series_number::text, 4, '0') as subscriber_id,
        (94770000000::bigint + series_number)::text as msisdn,
        case ((series_number - 1) % 3)
            when 0 then 'PLAN-BASIC'
            when 1 then 'PLAN-PLUS'
            else 'PLAN-PREMIUM'
        end as plan_id
    from generate_series(1, 40) as series_number
)
insert into public.subscribers (
    subscriber_id,
    msisdn,
    full_name_encrypted,
    email_encrypted,
    nic_encrypted,
    plan_id,
    account_status
)
select
    subscriber_id,
    msisdn,
    null,
    null,
    null,
    plan_id,
    'active'
from synthetic_subscribers
on conflict (subscriber_id) do update
set
    msisdn = excluded.msisdn,
    plan_id = excluded.plan_id,
    account_status = excluded.account_status,
    updated_at = now();

-- Verification result should be 40 after the first run.
select count(*) as synthetic_subscriber_count
from public.subscribers
where subscriber_id like 'SUB-%';
