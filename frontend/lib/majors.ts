/**
 * The institution's major keys and display labels, shared between the
 * manual-entry form (frontend/app/page.tsx) and Ask Fork's chat surfaces
 * (path-aware navigation pills need a real display name, not a raw major
 * key like "computer_science").
 *
 * Listed here rather than fetched because the backend has no endpoint for
 * them yet — see the longer note that used to live next to this constant
 * in page.tsx: this list already drifted out of sync with the data once
 * (it used to include "psychology", "nursing", and "mechanical_engineering",
 * which Stage 3's data work turned into a clarification case, an
 * unsupported case, and a renamed key respectively — see
 * backend/decision_paths/change_major/major_resolution.py). Worth an
 * endpoint eventually so this can't drift again.
 */
export const MAJORS = [
  { key: "computer_science", label: "Computer Science" },
  { key: "information_technology", label: "Information Technology" },
  { key: "business_administration", label: "Business Administration (BBA)" },
  { key: "psychology_ba", label: "Psychology (B.A.)" },
  { key: "psychology_bs", label: "Psychology (B.S.)" },
  { key: "mechanical_energy_engineering", label: "Mechanical & Energy Engineering" },
];

const MAJORS_BY_KEY = new Map(MAJORS.map((m) => [m.key, m.label]));

/** A real display label for a major key, or the raw key itself if it's
 * not one of the known majors (e.g. institution data has grown since this
 * list was last updated) -- never throws, always renders something. */
export function majorLabel(key: string): string {
  return MAJORS_BY_KEY.get(key) ?? key;
}
