import re
from typing import Dict, List, Tuple


POLICY_VERSION = "research-interest-v1"


def _pattern(*phrases: str) -> re.Pattern:
    parts = [re.escape(phrase).replace(r"\ ", r"[\s-]+") for phrase in phrases]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])", re.I)


POSITIVE_RULES = [
    ("galaxy-galaxy strong lensing", 70, True, _pattern("galaxy-galaxy lens", "galaxy galaxy lens", "galaxy-galaxy strong lens", "galaxy galaxy strong lens", "galaxy-scale strong lens")),
    ("strong gravitational lensing", 55, True, _pattern("strong gravitational lens", "strong gravitational lenses", "strong lens", "strong lenses", "strong lensing", "strong lens system", "strongly lensed")),
    ("gravitational lens modelling", 28, False, _pattern("lens model", "lensing model", "gravitational lens")),
    ("high-redshift galaxy dynamics", 34, False, _pattern("high-redshift kinematics", "high redshift kinematics", "high-redshift dynamics", "high redshift dynamics", "resolved kinematics")),
    ("high-redshift polarization", 32, False, _pattern("high-redshift polarization", "high redshift polarization", "high-redshift polarisation", "high redshift polarisation")),
    ("high-redshift multi-phase gas", 34, False, _pattern("high-redshift multi-phase gas", "high redshift multi-phase gas", "high-redshift multiphase gas", "high redshift multiphase gas")),
    ("multi-phase gas", 16, False, _pattern("multi-phase gas", "multiphase gas", "multiple gas phases")),
    ("galaxy polarization", 16, False, _pattern("galaxy polarization", "galaxy polarisation", "polarized galaxy", "polarised galaxy")),
    ("dusty high-redshift galaxies", 14, False, _pattern("dusty star-forming galaxy", "dusty high-redshift", "submillimeter galaxy")),
]

NEGATIVE_RULES = [
    ("stellar physics", -32, _pattern("stellar physics", "stellar evolution", "stellar population", "stellar populations", "stellar halo", "stellar-mass", "asteroseismology", "stellar atmosphere", "binary star", "stellar flare", "star cluster", "globular cluster", "planetary nebula", "galactic disk", "milky way")),
    ("pure cosmology", -30, _pattern("primordial power spectrum", "inflationary cosmology", "cosmological parameter", "large-scale structure cosmology", "modified gravity cosmology", "cmb power spectrum", "cmb lensing power spectrum", "hubble tension", "primordial non-gaussianity", "homogeneity scale", "dark energy", "cosmic strings")),
    ("particle physics", -38, _pattern("particle physics", "dark photon", "axion", "supersymmetry", "beyond the standard model")),
    ("neutrino physics", -45, _pattern("neutrino", "neutrinos")),
    ("solar or Solar System", -45, _pattern("solar physics", "solar flare", "solar wind", "solar corona", "solar system", "asteroid", "comet", "planetary science")),
    ("Galactic molecular cloud", -32, _pattern("galactic molecular cloud", "molecular cloud", "polaris flare", "galactic cirrus")),
    ("theoretical accretion prescription", -28, _pattern("bondi accretion", "accretion rate prescription", "black hole accretion prescription")),
    ("weak-lensing cosmology", -30, _pattern("weak lensing power spectrum", "lensing magnification", "cosmic shear", "shear-shear correlation")),
    ("cosmological statistics", -28, _pattern("growth rate measurement", "power spectrum turnover", "field statistics", "cosmological inference", "inhomogeneous curvature")),
    ("cluster gas rather than high-z galaxy gas", -18, _pattern("intracluster medium", "galaxy cluster gas")),
]

TOPIC_RULES = [
    ("Galaxy-Galaxy Strong Lensing", _pattern("galaxy-galaxy lens", "galaxy galaxy lens", "galaxy-galaxy strong lens", "galaxy galaxy strong lens", "galaxy-scale strong lens")),
    ("Strong Gravitational Lensing", _pattern("strong gravitational lens", "strong gravitational lenses", "strong lens", "strong lenses", "strong lensing", "strong lens system", "strongly lensed")),
    ("High-redshift Galaxy Dynamics", _pattern("high-redshift kinematics", "high redshift kinematics", "high-redshift dynamics", "high redshift dynamics", "resolved kinematics")),
    ("High-redshift Polarization", _pattern("high-redshift polarization", "high redshift polarization", "high-redshift polarisation", "high redshift polarisation")),
    ("High-redshift Multi-phase Gas", _pattern("high-redshift multi-phase gas", "high redshift multi-phase gas", "high-redshift multiphase gas", "high redshift multiphase gas")),
    ("Multi-phase and Molecular Gas", _pattern("multi-phase gas", "multiphase gas", "molecular gas", "cold gas", "circumgalactic gas")),
    ("Dust and ISM", _pattern("dust", "dusty", "interstellar medium", "ism", "submillimeter galaxy")),
    ("Galaxy Evolution", _pattern("galaxy evolution", "galaxy formation", "star-forming galaxy")),
]


def paper_text(paper: Dict) -> str:
    values = [paper.get("title", ""), paper.get("summary", ""), paper.get("categories", [])]
    return " ".join(str(value) for value in values).lower()


def evaluate_policy(paper: Dict) -> Dict:
    text = paper_text(paper)
    title_text = str(paper.get("title", "")).lower()
    summary_text = str(paper.get("summary", "")).lower()
    adjustments: List[Dict] = []
    mandatory = False
    positive_total = 0
    for label, points, force, pattern in POSITIVE_RULES:
        if pattern.search(text):
            adjustments.append({"label": label, "points": points})
            positive_total += points
            if force:
                central_in_title = bool(pattern.search(title_text))
                repeated_in_abstract = len(pattern.findall(summary_text)) >= 2
                mandatory = mandatory or label == "galaxy-galaxy strong lensing" or central_in_title or repeated_in_abstract

    negative_total = 0
    if not mandatory:
        for label, points, pattern in NEGATIVE_RULES:
            if pattern.search(text):
                adjustments.append({"label": label, "points": points})
                negative_total += points

    combo = 0
    has_lens = bool(_pattern("strong lens", "strong lenses", "strong lensing", "strongly lensed", "strong gravitational lens").search(text))
    has_high_z = bool(_pattern("high-redshift", "high redshift", "cosmic noon", "z > 1", "z>1").search(text))
    has_dynamics = bool(_pattern("kinematics", "dynamics", "rotation curve", "velocity field").search(text))
    has_galaxy = bool(_pattern("galaxy", "galaxies", "circumgalactic").search(text))
    has_gas = bool(_pattern("molecular gas", "cold gas", "multi-phase gas", "multiphase gas", "dense gas").search(text))
    if has_lens and has_high_z and has_dynamics:
        combo = 45
        mandatory = True
        adjustments.append({"label": "strong lensing + high-z dynamics", "points": combo})
    if has_galaxy and has_gas:
        gas_points = 20 if has_high_z else 10
        positive_total += gas_points
        adjustments.append({"label": "high-z galaxy gas" if has_high_z else "galaxy gas", "points": gas_points})

    score = max(0, min(100, 25 + positive_total + negative_total + combo))
    tier = "must-read" if mandatory else "recommended" if score >= 42 else "archive"
    return {
        "score": score,
        "tier": tier,
        "mandatory": mandatory,
        "adjustments": adjustments,
        "policy_version": POLICY_VERSION,
    }


def classify_topics(paper: Dict) -> List[str]:
    text = paper_text(paper)
    topics = [label for label, pattern in TOPIC_RULES if pattern.search(text)]
    return topics or ["Other Selected Research"]
