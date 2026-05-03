-- Pushkey Supabase setup — run this in your Supabase SQL Editor
-- ─────────────────────────────────────────────────────────────

-- 1. Waitlist table (for Vault Key USB and future "notify me" signups)
CREATE TABLE IF NOT EXISTS waitlist (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email       text NOT NULL,
  source      text NOT NULL DEFAULT 'general',
  created_at  timestamptz NOT NULL DEFAULT now(),
  notes       text
);

-- Make email + source unique so duplicate signups don't pile up
CREATE UNIQUE INDEX IF NOT EXISTS waitlist_email_source_idx
  ON waitlist (lower(email), source);

-- Enable row-level security
ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

-- Allow anonymous INSERTs (so the public website can submit signups via anon key)
CREATE POLICY waitlist_insert_anon
  ON waitlist FOR INSERT TO anon
  WITH CHECK (true);

-- Only authenticated/service-role users can read the waitlist
CREATE POLICY waitlist_select_auth
  ON waitlist FOR SELECT TO authenticated
  USING (true);
