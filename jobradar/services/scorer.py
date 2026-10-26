"""
Multi-Track Persona Scoring Engine.

Evaluates normalized Job listings against configured career tracks, location bonuses,
seniority multipliers, and exclusion gatekeepers.
Produces granular, explainable audit logs for every evaluation.
"""

from __future__ import annotations

import re
from typing import Optional
from jobradar.config import AppConfig, ScoringConfig
from jobradar.domain.models import Job, ScoreBreakdown, TrackScore


def build_keyword_pattern(keyword: str) -> re.Pattern:
    """
    Compile word-boundary regular expressions for keywords, handling special
    tech symbols (e.g., '.net', 'c#', 'm-pesa', 'go', 'tax') to avoid false positives.
    """
    kw = keyword.strip().lower()

    if kw == ".net":
        return re.compile(r"(?:^|[^\w])\.net(?:[^\w]|$)", re.IGNORECASE)
    elif kw == "c#":
        return re.compile(r"(?:^|[^\w])c#(?=[^\w]|$)", re.IGNORECASE)
    elif kw == "asp.net":
        return re.compile(r"(?:^|[^\w])asp\.net(?:[^\w]|$)", re.IGNORECASE)
    elif kw in ("m-pesa", "mpesa"):
        return re.compile(r"\bm-?pesa\b", re.IGNORECASE)
    elif kw in ("go", "golang"):
        return re.compile(r"\b(?:golang|go(?:\s+(?:developer|engineer|backend|fullstack|stack|lang|programmer))?)\b", re.IGNORECASE)
    elif kw == "qa":
        return re.compile(r"\bqa\b", re.IGNORECASE)
    elif kw == "tax":
        return re.compile(r"\btax\b", re.IGNORECASE)
    else:
        # Standard phrase/word boundary
        escaped = re.escape(kw)
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


class JobScorer:
    """Scoring engine evaluating jobs against multi-track profile personas."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.scoring_cfg: ScoringConfig = config.scoring
        self.min_score = config.pipeline.min_score
        self.near_miss_delta = config.pipeline.near_miss_delta

        # Pre-compile keyword patterns for maximum performance
        self._compiled_tracks: dict[str, dict[str, tuple[float, re.Pattern]]] = {}
        for track_id, track in self.scoring_cfg.tracks.items():
            self._compiled_tracks[track_id] = {
                kw: (weight, build_keyword_pattern(kw))
                for kw, weight in track.keywords.items()
            }

        self._compiled_exclusions = [
            (ex, build_keyword_pattern(ex)) for ex in self.scoring_cfg.exclude_keywords
        ]
        self._compiled_locations = [
            (loc, weight, build_keyword_pattern(loc))
            for loc, weight in self.scoring_cfg.locations.items()
        ]
        self._compiled_seniority = [
            (sen, weight, build_keyword_pattern(sen))
            for sen, weight in self.scoring_cfg.seniority.items()
        ]
        self._compiled_title_any = [
            (gate, build_keyword_pattern(gate)) for gate in self.scoring_cfg.title_any
        ]

    def score(self, job: Job) -> ScoreBreakdown:
        """Score a job listing and return an explainable breakdown."""
        title = job.title
        desc = job.description or ""
        location = job.location or ""
        full_text = f"{title}\n{desc}"

        # 1. Title Gate Check (if title_any is configured)
        if self._compiled_title_any:
            matched_title_any = any(pat.search(title) for _, pat in self._compiled_title_any)
            if not matched_title_any:
                return ScoreBreakdown(
                    best_track_id="none",
                    best_track_name="None",
                    track_score=0.0,
                    final_score=0.0,
                    is_match=False,
                    is_near_miss=False,
                    details="Disqualified: Title does not match any 'title_any' gateway keywords.",
                )

        # 2. Exclusions & Disqualifiers
        penalties = 0.0
        matched_penalties: list[str] = []
        for ex_kw, pat in self._compiled_exclusions:
            # Heavy penalty if exclusion is explicitly in title
            if pat.search(title):
                penalties += 20.0
                matched_penalties.append(f"Title contains '{ex_kw}' (-20)")
            # Moderate deduction if found in description
            elif pat.search(desc):
                penalties += 5.0
                matched_penalties.append(f"Description contains '{ex_kw}' (-5)")

        # 3. Multi-Track Persona Evaluation
        best_track_id = "none"
        best_track_name = "General"
        best_track_score = 0.0
        best_track_matches: list[str] = []

        for track_id, track_kw_map in self._compiled_tracks.items():
            track_name = self.scoring_cfg.tracks[track_id].name
            current_track_score = 0.0
            current_matches: list[str] = []

            for kw, (weight, pat) in track_kw_map.items():
                title_match = bool(pat.search(title))
                desc_match = bool(pat.search(desc))

                if title_match:
                    # Full weight for title match
                    current_track_score += weight
                    current_matches.append(f"{kw} [title: +{weight}]")
                elif desc_match:
                    # Half weight for description match
                    half_weight = round(weight / 2.0, 2)
                    current_track_score += half_weight
                    current_matches.append(f"{kw} [desc: +{half_weight}]")

            if current_track_score > best_track_score:
                best_track_score = current_track_score
                best_track_id = track_id
                best_track_name = track_name
                best_track_matches = current_matches

        # 4. Universal Bonuses (Location & Seniority)
        location_bonus = 0.0
        matched_locations: list[str] = []
        for loc, weight, pat in self._compiled_locations:
            # Check location field, title, or full text
            if pat.search(location) or pat.search(full_text):
                location_bonus += weight
                matched_locations.append(f"{loc} (+{weight})")

        seniority_bonus = 0.0
        matched_seniority: list[str] = []
        for sen, weight, pat in self._compiled_seniority:
            # Seniority checked in title for accuracy
            if pat.search(title):
                seniority_bonus += weight
                matched_seniority.append(f"{sen} (+{weight})")

        # 5. Calculate Final Score
        raw_final = (best_track_score + location_bonus + seniority_bonus) - penalties
        final_score = max(0.0, round(raw_final, 2))

        # 6. Match & Near-Miss Thresholds (Requires at least one tech track keyword match)
        has_tech_match = best_track_score > 0
        is_match = has_tech_match and (final_score >= self.min_score)
        is_near_miss = has_tech_match and ((self.min_score - self.near_miss_delta) <= final_score < self.min_score)

        # 7. Human-Readable Audit Trail
        details_parts = [
            f"Persona: {best_track_name} (Track Score: {best_track_score})",
        ]
        if best_track_matches:
            details_parts.append(f"Keywords: {', '.join(best_track_matches)}")
        if matched_locations:
            details_parts.append(f"Location: {', '.join(matched_locations)}")
        if matched_seniority:
            details_parts.append(f"Seniority: {', '.join(matched_seniority)}")
        if matched_penalties:
            details_parts.append(f"Penalties: {', '.join(matched_penalties)}")

        details_parts.append(f"Final Score: {final_score} (Min: {self.min_score})")
        details = " | ".join(details_parts)

        return ScoreBreakdown(
            best_track_id=best_track_id,
            best_track_name=best_track_name,
            track_score=best_track_score,
            location_bonus=location_bonus,
            matched_locations=matched_locations,
            seniority_bonus=seniority_bonus,
            matched_seniority=matched_seniority,
            penalties=penalties,
            matched_penalties=matched_penalties,
            final_score=final_score,
            is_match=is_match,
            is_near_miss=is_near_miss,
            details=details,
        )
