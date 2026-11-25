-- One row per page load. visitor: truncated HMAC of the browser's random ID.
CREATE TABLE IF NOT EXISTS visits (
  visit TEXT PRIMARY KEY,
  visitor TEXT NOT NULL,
  day TEXT NOT NULL,
  referrer TEXT NOT NULL DEFAULT ''
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS visits_day ON visits(day);
-- One row per completed build. previous: release of the PPF being replaced, '' if none/unknown.
-- known: 1 when the previous PPF's settings were read, so build_mods.was is meaningful.
-- at: UTC time to the second; NULL on builds recorded before it existed.
CREATE TABLE IF NOT EXISTS builds (
  build TEXT PRIMARY KEY,
  visit TEXT NOT NULL REFERENCES visits(visit),
  release TEXT NOT NULL,
  previous TEXT NOT NULL,
  output TEXT NOT NULL CHECK (output IN ('ppf', 'disc')),
  source TEXT NOT NULL CHECK (source IN ('bin', 'chd')),
  folder INTEGER NOT NULL,
  known INTEGER NOT NULL,
  at TEXT
) WITHOUT ROWID;
-- One row per mod in the build or in the PPF it replaces. options/was: sorted,
-- comma-joined option tokens; NULL = mod not on. changed: the option keys
-- (`speed` of `speed=3`) not at the release's default, as the patcher saw
-- them; NULL when unknown (mod off, or recorded before it existed).
CREATE TABLE IF NOT EXISTS build_mods (
  build TEXT NOT NULL REFERENCES builds(build),
  mod TEXT NOT NULL,
  options TEXT,
  was TEXT,
  changed TEXT,
  PRIMARY KEY (build, mod)
) WITHOUT ROWID;
