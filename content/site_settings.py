"""Homepage values that staff edit in Admin → Settings → Business settings and the public site reads.

Only the keys listed here are ever exposed publicly; every other Setting (advance %, legal details, ...) stays private.
"""
HOMEPAGE_STATS_KEY = 'homepage.stats'

# The numbers that used to be hard-coded on the homepage. Created once per operator so they appear in Business
# settings; the PLACEHOLDER note is removed automatically when someone saves the setting.
DEFAULT_HOMEPAGE_STATS = [
    {'value': 12500, 'suffix': '+', 'label': 'Community members'},
    {'value': 480, 'suffix': '+', 'label': 'Weekend experiences hosted'},
    {'value': 36, 'suffix': '', 'label': 'Hidden spots explored'},
    {'value': 4.8, 'suffix': '/5', 'decimals': 1, 'label': 'Average experience rating'},
]
HOMEPAGE_STATS_DESCRIPTION = (
    'Homepage numbers. A list of {"value": number, "suffix": "+", "decimals": 0, "label": "text"}; '
    'up to 4 are shown. Use [] to hide the section. PLACEHOLDER: replace with real numbers.'
)


def ensure_homepage_stats():
    """Return the homepage stats Setting for the current operator, creating it with the defaults if missing."""
    from core.models import Setting
    setting, _ = Setting.objects.get_or_create(
        key=HOMEPAGE_STATS_KEY,
        defaults={'value': DEFAULT_HOMEPAGE_STATS, 'description': HOMEPAGE_STATS_DESCRIPTION},
    )
    return setting


def clean_stats(value):
    """Keep only well-formed entries so a typo in the admin cannot break the homepage."""
    if not isinstance(value, list):
        return []
    stats = []
    for item in value:
        if not isinstance(item, dict):
            continue
        number, label = item.get('value'), item.get('label')
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not isinstance(label, str) or not label.strip():
            continue
        decimals = item.get('decimals', 0)
        stats.append({
            'value': number,
            'label': label.strip()[:80],
            'suffix': str(item.get('suffix', ''))[:6],
            'decimals': decimals if isinstance(decimals, int) and 0 <= decimals <= 2 else 0,
        })
    return stats[:4]
